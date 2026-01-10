from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta
import uuid

from apps.events.models import (
    Event, EventType, EventSettings, EventStatusChoices,
    EventAuthorization, EventAuthorizationStatusChoices,
    EventPermission, EventPermissionAssignment, EventPermissionCategoryChoices,
    EventRole, EventRoleAssignment, EventRoleCategoryChoices,
    EventStaff, EventStaffAvailability,
    EventReview,
    EventQuestion, EventQuestionTypeChoices, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice
)
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee

User = get_user_model()


class BaseEventAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.staff_user = User.objects.create_user(
            username='staffuser',
            email='staffuser@example.com',
            password='testpass123',
            is_staff=True
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation description',
            created_by=self.user
        )
        
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            description='Conference events',
            created_by=self.user
        )
        
        self.start_time = timezone.now() + timedelta(days=30)
        self.end_time = timezone.now() + timedelta(days=32)
        
        self.event = Event.objects.create(
            title='Test Conference 2025',
            display_code='TC2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED
        )


class EventTypeAPITest(BaseEventAPITestCase):
    def test_list_event_types_unauthenticated(self):
        response = self.client.get('/api/event/types/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_event_types_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/types/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_event_type(self):
        response = self.client.get(f'/api/event/types/{self.event_type.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Conference')
        self.assertEqual(response.data['code'], 'CONF')
    
    def test_create_event_type_authenticated(self):
        self.client.force_authenticate(user=self.user)
        data = {
            'title': 'Workshop',
            'code': 'WORK',
            'description': 'Workshop events',
            'created_by': self.user.id
        }
        response = self.client.post('/api/event/types/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Workshop')
    
    def test_create_event_type_unauthenticated(self):
        data = {
            'title': 'Workshop',
            'code': 'WORK',
            'description': 'Workshop events'
        }
        response = self.client.post('/api/event/types/', data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_search_event_types(self):
        response = self.client.get('/api/event/types/?search=Conference')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class EventAPITest(BaseEventAPITestCase):
    def test_list_events_unauthenticated(self):
        response = self.client.get('/api/event/list/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_events_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/list/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_event(self):
        response = self.client.get(f'/api/event/list/{self.event.event_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Test Conference 2025')
        self.assertIn('event_type_details', response.data)
    
    def test_create_event_authenticated(self):
        self.client.force_authenticate(user=self.user)
        data = {
            'title': 'New Event',
            'display_code': 'NE2025',
            'event_type': self.event_type.id,
            'start_datetime': (timezone.now() + timedelta(days=60)).isoformat(),
            'end_datetime': (timezone.now() + timedelta(days=62)).isoformat(),
            'organisation': self.organisation.id,
            'status': EventStatusChoices.DRAFTING,
            'timezone': 'Europe/London'
        }
        response = self.client.post('/api/event/list/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'New Event')
    
    def test_create_event_unauthenticated(self):
        data = {
            'title': 'New Event',
            'display_code': 'NE2025',
            'event_type': self.event_type.id,
            'start_datetime': (timezone.now() + timedelta(days=60)).isoformat(),
            'end_datetime': (timezone.now() + timedelta(days=62)).isoformat(),
            'organisation': self.organisation.id
        }
        response = self.client.post('/api/event/list/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_update_event(self):
        self.client.force_authenticate(user=self.user)
        data = {
            'title': 'Updated Conference',
            'display_code': 'TC2025',
            'event_type': self.event_type.id,
            'start_datetime': self.start_time.isoformat(),
            'end_datetime': self.end_time.isoformat(),
            'organisation': self.organisation.id,
            'status': EventStatusChoices.OPEN,
            'timezone': 'Europe/London',
            'created_by': self.user.id
        }
        response = self.client.put(f'/api/event/list/{self.event.event_id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Conference')
    
    def test_filter_events_by_status(self):
        response = self.client.get(f'/api/event/list/?status={EventStatusChoices.PUBLISHED}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for event in response.data['results']:
            self.assertEqual(event['status'], EventStatusChoices.PUBLISHED)
    
    def test_filter_events_by_event_type(self):
        response = self.client.get(f'/api/event/list/?event_type={self.event_type.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_search_events(self):
        response = self.client.get('/api/event/list/?search=Conference')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_upcoming_events_action(self):
        response = self.client.get('/api/event/list/upcoming/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_ongoing_events_action(self):
        response = self.client.get('/api/event/list/ongoing/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_event_settings_action(self):
        self.event.settings.payment_enabled = True
        self.event.settings.save()
        response = self.client.get(f'/api/event/list/{self.event.event_id}/settings/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['payment_enabled'])


class EventAuthorizationAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.authorization = EventAuthorization.objects.create(
            event=self.event,
            reviewed_by=self.user,
            status=EventAuthorizationStatusChoices.APPROVED,
            reason='Event approved'
        )
    
    def test_list_authorizations_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/authorizations/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_list_authorizations_unauthenticated(self):
        response = self.client.get('/api/event/authorizations/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_retrieve_authorization(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/authorizations/{self.authorization.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], EventAuthorizationStatusChoices.APPROVED)
    
    def test_create_authorization(self):
        self.client.force_authenticate(user=self.staff_user)
        event2 = Event.objects.create(
            title='Another Event',
            display_code='AE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=self.start_time,
            end_datetime=self.end_time,
            organisation=self.organisation
        )
        data = {
            'event': event2.id,
            'status': EventAuthorizationStatusChoices.PENDING,
            'reason': 'Under review'
        }
        response = self.client.post('/api/event/authorizations/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_authorizations_by_event(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/authorizations/?event={self.event.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class EventPermissionAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.permission = EventPermission.objects.create(
            name='Can Edit Event',
            code='can_edit_event',
            category=EventPermissionCategoryChoices.CONTENT_MANAGEMENT
        )
    
    def test_list_permissions_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/permissions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_permission(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/permissions/{self.permission.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Can Edit Event')
    
    def test_create_permission(self):
        self.client.force_authenticate(user=self.staff_user)
        data = {
            'name': 'Can Delete Event',
            'code': 'can_delete_event',
            'category': EventPermissionCategoryChoices.GENERAL
        }
        response = self.client.post('/api/event/permissions/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class EventRoleAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.role = EventRole.objects.create(
            name='Event Coordinator',
            code='COORD',
            category=EventRoleCategoryChoices.COORDINATOR
        )
    
    def test_list_roles_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/roles/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_role(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/roles/{self.role.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Event Coordinator')
    
    def test_create_role(self):
        self.client.force_authenticate(user=self.staff_user)
        data = {
            'name': 'Volunteer',
            'code': 'VOL',
            'category': EventRoleCategoryChoices.VOLUNTEER
        }
        response = self.client.post('/api/event/roles/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class EventStaffAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.staff_member = EventStaff.objects.create(
            event=self.event,
            user=self.staff_user,
            assigned_by=self.user,
            notes='Lead coordinator'
        )
    
    def test_list_staff_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/staff/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_staff(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/staff/{self.staff_member.staff_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['notes'], 'Lead coordinator')
    
    def test_create_staff(self):
        self.client.force_authenticate(user=self.user)
        new_user = User.objects.create_user(
            username='newstaff',
            email='newstaff@example.com',
            password='testpass123'
        )
        data = {
            'event': self.event.id,
            'user': new_user.id,
            'notes': 'Assistant'
        }
        response = self.client.post('/api/event/staff/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_staff_by_event(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/staff/?event={self.event.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class EventReviewAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.review = EventReview.objects.create(
            event=self.event,
            user=self.user,
            rating=5,
            comment='Great event!',
            approved=True
        )
    
    def test_list_reviews_unauthenticated(self):
        response = self.client.get('/api/event/reviews/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_list_reviews_shows_only_approved(self):
        EventReview.objects.create(
            event=self.event,
            user=self.staff_user,
            rating=3,
            comment='Needs improvement',
            approved=False
        )
        response = self.client.get('/api/event/reviews/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for review in response.data['results']:
            self.assertTrue(review['approved'])
    
    def test_retrieve_review(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/reviews/{self.review.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['rating'], 5)
    
    def test_create_review(self):
        self.client.force_authenticate(user=self.staff_user)
        data = {
            'event': self.event.id,
            'rating': 4,
            'comment': 'Good event'
        }
        response = self.client.post('/api/event/reviews/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['rating'], 4)
    
    def test_filter_reviews_by_event(self):
        response = self.client.get(f'/api/event/reviews/?event={self.event.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_approve_review_action(self):
        self.client.force_authenticate(user=self.staff_user)
        unapproved_review = EventReview.objects.create(
            event=self.event,
            user=self.staff_user,
            rating=3,
            comment='OK',
            approved=False
        )
        response = self.client.post(f'/api/event/reviews/{unapproved_review.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['approved'])


class EventQuestionAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.question = EventQuestion.objects.create(
            event=self.event,
            question_title='Dietary Requirements',
            question_body='Do you have any dietary requirements?',
            question_type=EventQuestionTypeChoices.LONG_ANSWER,
            required=True,
            order=1
        )
    
    def test_list_questions_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/questions/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_question(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/questions/{self.question.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['question_title'], 'Dietary Requirements')
    
    def test_create_question(self):
        self.client.force_authenticate(user=self.user)
        data = {
            'event': self.event.id,
            'question_title': 'T-Shirt Size',
            'question_body': 'What is your t-shirt size?',
            'question_type': EventQuestionTypeChoices.SINGLE_CHOICE,
            'required': True,
            'order': 2
        }
        response = self.client.post('/api/event/questions/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_questions_by_event(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/questions/?event={self.event.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class EventQuestionOptionAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.question = EventQuestion.objects.create(
            event=self.event,
            question_title='T-Shirt Size',
            question_body='What is your t-shirt size?',
            question_type=EventQuestionTypeChoices.SINGLE_CHOICE,
            required=True,
            order=1
        )
        self.option = EventQuestionOption.objects.create(
            question=self.question,
            option_text='Small',
            order=1
        )
    
    def test_list_options_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/question-options/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_option(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/question-options/{self.option.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['option_text'], 'Small')
    
    def test_create_option(self):
        self.client.force_authenticate(user=self.user)
        data = {
            'question': str(self.question.id),
            'option_text': 'Medium',
            'order': 2
        }
        response = self.client.post('/api/event/question-options/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class EventQuestionAnswerAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.attendee = Attendee.objects.create(
            first_name='John',
            last_name='Doe',
            event=self.event,
            date_of_birth=timezone.now().date() - timedelta(days=365*30),
            user=self.user,
            defined_by=self.user
        )
        self.question = EventQuestion.objects.create(
            event=self.event,
            question_title='Dietary Requirements',
            question_body='Do you have any dietary requirements?',
            question_type=EventQuestionTypeChoices.LONG_ANSWER,
            required=True,
            order=1
        )
        self.answer = EventQuestionAnswer.objects.create(
            question=self.question,
            attendee=self.attendee,
            answer_text='No dietary requirements'
        )
    
    def test_list_answers_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/question-answers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_retrieve_answer(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/question-answers/{self.answer.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['answer_text'], 'No dietary requirements')
    
    def test_create_answer(self):
        self.client.force_authenticate(user=self.user)
        question2 = EventQuestion.objects.create(
            event=self.event,
            question_title='Emergency Contact',
            question_body='Emergency contact name',
            question_type=EventQuestionTypeChoices.SHORT_ANSWER,
            required=True,
            order=2
        )
        data = {
            'question': str(question2.id),
            'attendee': self.attendee.id,
            'answer_text': 'Jane Doe'
        }
        response = self.client.post('/api/event/question-answers/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_answers_by_question(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/question-answers/?question={self.question.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
