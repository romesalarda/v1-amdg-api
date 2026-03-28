from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta
import uuid
from io import BytesIO
from PIL import Image

from apps.events.models import (
    Event, EventType, EventSettings, EventStatusChoices,
    EventAuthorization, EventAuthorizationStatusChoices,
    EventPermission, EventPermissionAssignment, EventPermissionCategoryChoices,
    EventRole, EventRoleAssignment, EventRoleCategoryChoices,
    EventStaff, EventStaffAvailability, EventStaffInvite,
    EventReview,
    EventQuestion, EventQuestionTypeChoices, EventQuestionOption,
    EventQuestionAnswer, EventQuestionAnswerChoice, EventVenue
)
from apps.common.models import AvailabilityWindow, Resource, AvailabilityTypeChoices, ResourceTypeChoices
from apps.organisations.models import Organisation
from apps.attendee.models import Attendee
from apps.locations.models import POI, Venue, POITypeChoice

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
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/')
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
        response = self.client.put(f'/api/event/list/{self.event.url_safe_title}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Conference')

    def test_partial_update_event_status_back_to_drafting(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f'/api/event/list/{self.event.url_safe_title}/',
            {'status': EventStatusChoices.DRAFTING},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, EventStatusChoices.DRAFTING)

    def test_partial_update_postponed_event_status_to_published(self):
        self.client.force_authenticate(user=self.user)
        self.event.status = EventStatusChoices.POSTPONED
        self.event.save(update_fields=['status'])

        response = self.client.patch(
            f'/api/event/list/{self.event.url_safe_title}/',
            {'status': EventStatusChoices.PUBLISHED},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, EventStatusChoices.PUBLISHED)

    def test_partial_update_postponed_event_status_to_open(self):
        self.client.force_authenticate(user=self.user)
        self.event.status = EventStatusChoices.POSTPONED
        self.event.save(update_fields=['status'])

        response = self.client.patch(
            f'/api/event/list/{self.event.url_safe_title}/',
            {'status': EventStatusChoices.OPEN},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, EventStatusChoices.OPEN)
    
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
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/settings/')
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
            'event': event2.event_id,
            'status': EventAuthorizationStatusChoices.PENDING,
            'reason': 'Under review'
        }
        response = self.client.post('/api/event/authorizations/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_authorizations_by_event(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/authorizations/?event={self.event.url_safe_title}')
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
            'event': self.event.event_id,
            'user': new_user.id,
            'notes': 'Assistant'
        }
        response = self.client.post('/api/event/staff/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_staff_by_event(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/staff/?event={self.event.url_safe_title}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_remove_staff_action_deletes_non_creator_staff(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-staff/?staff_id={self.staff_member.staff_id}'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EventStaff.objects.filter(staff_id=self.staff_member.staff_id).exists())

    def test_remove_staff_action_blocks_event_creator_removal(self):
        creator_staff = EventStaff.objects.create(
            event=self.event,
            user=self.user,
            assigned_by=self.user,
            notes='Event creator'
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-staff/?staff_id={creator_staff.staff_id}'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        self.assertTrue(EventStaff.objects.filter(staff_id=creator_staff.staff_id).exists())

    def test_remove_staff_action_blocks_event_creator_removal_for_superuser(self):
        creator_staff = EventStaff.objects.create(
            event=self.event,
            user=self.user,
            assigned_by=self.user,
            notes='Event creator'
        )
        superuser = User.objects.create_superuser(
            username='superuser1',
            email='super1@example.com',
            password='testpass123'
        )

        self.client.force_authenticate(user=superuser)
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-staff/?staff_id={creator_staff.staff_id}'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        self.assertTrue(EventStaff.objects.filter(staff_id=creator_staff.staff_id).exists())

    def test_event_staff_destroy_blocks_event_creator_removal(self):
        creator_staff = EventStaff.objects.create(
            event=self.event,
            user=self.user,
            assigned_by=self.user,
            notes='Event creator'
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f'/api/event/staff/{creator_staff.staff_id}/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        self.assertTrue(EventStaff.objects.filter(staff_id=creator_staff.staff_id).exists())


class EventCreatorAssignmentImmutabilityAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        self.permission = EventPermission.objects.create(
            name='Can Manage Staff',
            code='can_manage_staff',
            category=EventPermissionCategoryChoices.STAFF_MANAGEMENT
        )
        self.role = EventRole.objects.create(
            name='Coordinator',
            code='CORD',
            category=EventRoleCategoryChoices.COORDINATOR
        )

    def test_permission_assignment_create_blocks_event_creator(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/event/permission-assignments/', {
            'event': self.event.event_id,
            'user': self.user.id,
            'permission': self.permission.id,
            'read_only': True,
            'allow_update': False,
            'allow_delete': False,
            'allow_create': False,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')

    def test_permission_assignment_update_blocks_event_creator_target(self):
        assignment = EventPermissionAssignment.objects.create(
            event=self.event,
            user=self.staff_user,
            permission=self.permission,
            assigned_by=self.user,
            read_only=True,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f'/api/event/permission-assignments/{assignment.id}/',
            {'user': self.user.id},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        assignment.refresh_from_db()
        self.assertEqual(assignment.user_id, self.staff_user.id)

    def test_permission_assignment_destroy_blocks_event_creator(self):
        assignment = EventPermissionAssignment.objects.create(
            event=self.event,
            user=self.user,
            permission=self.permission,
            assigned_by=self.user,
            read_only=True,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f'/api/event/permission-assignments/{assignment.id}/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        self.assertTrue(EventPermissionAssignment.objects.filter(id=assignment.id).exists())

    def test_role_assignment_create_blocks_event_creator(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/event/role-assignments/', {
            'event': self.event.event_id,
            'user': self.user.id,
            'role': self.role.id,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')

    def test_role_assignment_update_blocks_event_creator_target(self):
        assignment = EventRoleAssignment.objects.create(
            event=self.event,
            user=self.staff_user,
            role=self.role,
            assigned_by=self.user,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            f'/api/event/role-assignments/{assignment.id}/',
            {'user': self.user.id},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        assignment.refresh_from_db()
        self.assertEqual(assignment.user_id, self.staff_user.id)

    def test_role_assignment_destroy_blocks_event_creator(self):
        assignment = EventRoleAssignment.objects.create(
            event=self.event,
            user=self.user,
            role=self.role,
            assigned_by=self.user,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f'/api/event/role-assignments/{assignment.id}/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Event creator access is immutable')
        self.assertTrue(EventRoleAssignment.objects.filter(id=assignment.id).exists())


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
            'event': self.event.event_id,
            'rating': 4,
            'comment': 'Good event'
        }
        response = self.client.post('/api/event/reviews/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['rating'], 4)
    
    def test_filter_reviews_by_event(self):
        response = self.client.get(f'/api/event/reviews/?event={self.event.url_safe_title}')
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
            'event': self.event.event_id,
            'question_title': 'T-Shirt Size',
            'question_body': 'What is your t-shirt size?',
            'question_type': EventQuestionTypeChoices.SINGLE_CHOICE,
            'required': True,
            'order': 2,
            'options': [
                {'option_text': 'Small', 'order': 1},
                {'option_text': 'Medium', 'order': 2},
            ],
        }
        response = self.client.post('/api/event/questions/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_questions_by_event(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/questions/?event={self.event.url_safe_title}')
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
            'attendee': str(self.attendee.attendee_id),
            'answer_text': 'Jane Doe'
        }
        response = self.client.post('/api/event/question-answers/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_filter_answers_by_question(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/question-answers/?question={self.question.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class EventSoftDeleteAPITest(BaseEventAPITestCase):
    """Tests for event soft delete functionality"""
    
    def test_soft_delete_event_as_owner(self):
        """Test that event owner can soft delete an event"""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/soft-delete/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('deleted_at', response.data)
        
        # Verify event is soft deleted
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.deleted_at)
        self.assertEqual(self.event.deleted_by, self.user)
    
    def test_soft_delete_event_unauthorized(self):
        """Test that non-owner cannot soft delete event"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=other_user)
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/soft-delete/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_soft_delete_already_deleted_event(self):
        """Test that already deleted event returns error"""
        self.client.force_authenticate(user=self.user)
        self.event.soft_delete()
        
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/soft-delete/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_restore_soft_deleted_event(self):
        """Test restoring a soft deleted event"""
        self.client.force_authenticate(user=self.user)
        self.event.soft_delete()
        self.event.deleted_by = self.user
        self.event.save()
        
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/restore/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify event is restored
        self.event.refresh_from_db()
        self.assertIsNone(self.event.deleted_at)
        self.assertIsNone(self.event.deleted_by)
    
    def test_restore_event_unauthorized(self):
        """Test that non-owner cannot restore event"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=other_user)
        self.event.soft_delete()
        
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/restore/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EventAvailabilityWindowAPITest(BaseEventAPITestCase):
    """Tests for event availability window functionality"""
    
    def test_list_availability_windows(self):
        """Test listing availability windows for an event"""
        # Create some availability windows
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        window1 = AvailabilityWindow.objects.create(
            name='Registration Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=ct,
            target_id=self.event.id,
            available_from=timezone.now(),
            available_to=timezone.now() + timedelta(days=10)
        )
        
        window2 = AvailabilityWindow.objects.create(
            name='Payment Window',
            availability_type=AvailabilityTypeChoices.PAYMENT_WINDOW,
            target_type=ct,
            target_id=self.event.id,
            available_from=timezone.now(),
            available_to=timezone.now() + timedelta(days=5)
        )
        
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/availability-windows/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 2)
    
    def test_add_availability_window_authenticated(self):
        """Test adding an availability window as event owner"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Early Bird Registration',
            'description': 'Early bird pricing period',
            'availability_type': AvailabilityTypeChoices.REGISTRATION,
            'available_from': (timezone.now() + timedelta(days=1)).isoformat(),
            'available_to': (timezone.now() + timedelta(days=15)).isoformat(),
            'timezone': 'Europe/London'
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-availability-window/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Early Bird Registration')
        
        # Verify window was created
        self.assertEqual(self.event.availability_windows.count(), 1)
    
    def test_add_availability_window_invalid_dates(self):
        """Test adding availability window with invalid date range"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Invalid Window',
            'availability_type': AvailabilityTypeChoices.REGISTRATION,
            'available_from': (timezone.now() + timedelta(days=10)).isoformat(),
            'available_to': (timezone.now() + timedelta(days=5)).isoformat(),  # Before available_from
            'timezone': 'Europe/London'
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-availability-window/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('available_to', response.data)
    
    def test_add_availability_window_unauthorized(self):
        """Test that non-owner cannot add availability window"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=other_user)
        
        data = {
            'name': 'Test Window',
            'availability_type': AvailabilityTypeChoices.REGISTRATION,
            'available_from': timezone.now().isoformat(),
            'available_to': (timezone.now() + timedelta(days=10)).isoformat(),
            'timezone': 'Europe/London'
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-availability-window/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_remove_availability_window(self):
        """Test removing an availability window"""
        self.client.force_authenticate(user=self.user)
        
        # Create a window first
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        window = AvailabilityWindow.objects.create(
            name='Test Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=ct,
            target_id=self.event.id,
            available_from=timezone.now(),
            available_to=timezone.now() + timedelta(days=10)
        )
        
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-availability-window/?window_id={window.availability_id}'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify window was deleted
        self.assertEqual(self.event.availability_windows.count(), 0)
    
    def test_remove_availability_window_not_found(self):
        """Test removing non-existent availability window"""
        self.client.force_authenticate(user=self.user)
        
        fake_id = uuid.uuid4()
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-availability-window/?window_id={fake_id}'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class EventResourceAPITest(BaseEventAPITestCase):
    """Tests for event resource functionality"""
    
    def setUp(self):
        super().setUp()
        # Helper to create a test image file
        self.test_image = self._create_test_image()
        self.test_file = self._create_test_file()
    
    def _create_test_image(self):
        """Create a simple test image"""
        image = Image.new('RGB', (100, 100), color='red')
        image_io = BytesIO()
        image.save(image_io, format='JPEG')
        image_io.seek(0)
        return SimpleUploadedFile(
            'test_image.jpg',
            image_io.read(),
            content_type='image/jpeg'
        )
    
    def _create_test_file(self):
        """Create a simple test file"""
        return SimpleUploadedFile(
            'test_document.pdf',
            b'Test file content',
            content_type='application/pdf'
        )
    
    def test_list_resources(self):
        """Test listing resources for an event"""
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        # Create some resources
        Resource.objects.create(
            name='Test Document',
            resource_type=ResourceTypeChoices.DOCUMENT,
            target_type=ct,
            target_id=self.event.id,
            file=self._create_test_file(),
            added_by=self.user
        )
        
        Resource.objects.create(
            name='Test Link',
            resource_type=ResourceTypeChoices.LINK,
            target_type=ct,
            target_id=self.event.id,
            link='https://example.com',
            added_by=self.user
        )
        
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/resources/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 2)
    
    def test_add_resource_with_file(self):
        """Test adding a file resource to an event"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Event Schedule',
            'description': 'Conference schedule PDF',
            'resource_type': ResourceTypeChoices.DOCUMENT,
            'public': True,
            'file': self._create_test_file()
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-resource/',
            data,
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Event Schedule')
        self.assertEqual(response.data['resource_type'], ResourceTypeChoices.DOCUMENT)
        
        # Verify resource was created
        self.assertEqual(self.event.resources.count(), 1)
    
    def test_add_resource_with_link(self):
        """Test adding a link resource to an event"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Event Website',
            'description': 'Official event website',
            'resource_type': ResourceTypeChoices.LINK,
            'link': 'https://event-example.com',
            'public': True
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-resource/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['resource_type'], ResourceTypeChoices.LINK)
        self.assertIn('link', response.data)
    
    def test_add_resource_with_image(self):
        """Test adding an image resource to an event"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Venue Photo',
            'description': 'Photo of the venue',
            'resource_type': ResourceTypeChoices.IMAGE,
            'public': True,
            'image': self._create_test_image()
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-resource/',
            data,
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['resource_type'], ResourceTypeChoices.IMAGE)
    
    def test_add_resource_unauthorized(self):
        """Test that non-owner cannot add resources"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=other_user)
        
        data = {
            'name': 'Test Resource',
            'resource_type': ResourceTypeChoices.LINK,
            'link': 'https://example.com',
            'public': True
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-resource/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_add_resource_missing_required_field(self):
        """Test adding resource without required field based on type"""
        self.client.force_authenticate(user=self.user)
        
        # Try to add DOCUMENT without file
        data = {
            'name': 'Missing File',
            'resource_type': ResourceTypeChoices.DOCUMENT,
            'public': True
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-resource/',
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('file', response.data)
    
    def test_filter_resources_by_tag(self):
        """Test filtering resources by tag"""
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        Resource.objects.create(
            name='Landing Photo',
            resource_type=ResourceTypeChoices.IMAGE,
            tag='LANDING_PHOTO_MAIN',
            target_type=ct,
            target_id=self.event.id,
            image=self._create_test_image(),
            added_by=self.user
        )
        
        Resource.objects.create(
            name='Schedule PDF',
            resource_type=ResourceTypeChoices.DOCUMENT,
            tag='SCHEDULE',
            target_type=ct,
            target_id=self.event.id,
            file=self._create_test_file(),
            added_by=self.user
        )
        
        response = self.client.get(
            f'/api/event/list/{self.event.url_safe_title}/resources/?tag=LANDING_PHOTO_MAIN'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['tag'], 'LANDING_PHOTO_MAIN')
    
    def test_filter_resources_by_type(self):
        """Test filtering resources by resource type"""
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        Resource.objects.create(
            name='Document 1',
            resource_type=ResourceTypeChoices.DOCUMENT,
            target_type=ct,
            target_id=self.event.id,
            file=self._create_test_file(),
            added_by=self.user
        )
        
        Resource.objects.create(
            name='Link 1',
            resource_type=ResourceTypeChoices.LINK,
            target_type=ct,
            target_id=self.event.id,
            link='https://example.com',
            added_by=self.user
        )
        
        response = self.client.get(
            f'/api/event/list/{self.event.url_safe_title}/resources/?resource_type={ResourceTypeChoices.DOCUMENT}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['resource_type'], ResourceTypeChoices.DOCUMENT)
    
    def test_remove_resource(self):
        """Test removing a resource"""
        self.client.force_authenticate(user=self.user)
        
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        resource = Resource.objects.create(
            name='To Delete',
            resource_type=ResourceTypeChoices.LINK,
            target_type=ct,
            target_id=self.event.id,
            link='https://example.com',
            added_by=self.user
        )
        
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-resource/?resource_id={resource.id}'
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify resource was deleted
        self.assertEqual(self.event.resources.count(), 0)
    
    def test_remove_protected_resource(self):
        """Test that protected resources cannot be deleted"""
        self.client.force_authenticate(user=self.user)
        
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Event)
        
        resource = Resource.objects.create(
            name='Protected Resource',
            resource_type=ResourceTypeChoices.LINK,
            target_type=ct,
            target_id=self.event.id,
            link='https://example.com',
            added_by=self.user,
            protected=True
        )
        
        response = self.client.delete(
            f'/api/event/list/{self.event.url_safe_title}/remove-resource/?resource_id={resource.id}'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('protected', response.data['detail'].lower())


class EventLandingImageAPITest(BaseEventAPITestCase):
    """Tests for event landing image functionality"""
    
    def _create_test_image(self):
        """Create a simple test image"""
        image = Image.new('RGB', (100, 100), color='blue')
        image_io = BytesIO()
        image.save(image_io, format='JPEG')
        image_io.seek(0)
        return SimpleUploadedFile(
            'landing_image.jpg',
            image_io.read(),
            content_type='image/jpeg'
        )
    
    def test_add_landing_image_as_main(self):
        """Test adding a landing image as the main image"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Main Event Banner',
            'description': 'Main promotional banner',
            'image': self._create_test_image(),
            'is_main': 'true',
            'public': 'true'
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data,
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['tag'], 'LANDING_PHOTO_MAIN')
        
        # Verify using event's landing images property
        self.assertEqual(self.event.landing_images.count(), 1)
        self.assertIsNotNone(self.event.main_landing_image)
    
    def test_add_landing_image_as_secondary(self):
        """Test adding a landing image as secondary"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'Secondary Banner',
            'description': 'Alternative banner',
            'image': self._create_test_image(),
            'is_main': 'false',
            'public': 'true'
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data,
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['tag'], 'LANDING_PHOTO_SECONDARY')
    
    def test_add_multiple_main_images_replaces_previous(self):
        """Test that adding a new main image demotes the previous main to secondary"""
        self.client.force_authenticate(user=self.user)
        
        # Add first main image
        data1 = {
            'name': 'First Main',
            'image': self._create_test_image(),
            'is_main': 'true',
            'public': 'true'
        }
        response1 = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data1,
            format='multipart'
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        
        # Add second main image
        data2 = {
            'name': 'Second Main',
            'image': self._create_test_image(),
            'is_main': 'true',
            'public': 'true'
        }
        response2 = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data2,
            format='multipart'
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        
        # Verify only one main image exists
        self.event.refresh_from_db()
        main_images = self.event.resources.filter(tag='LANDING_PHOTO_MAIN')
        self.assertEqual(main_images.count(), 1)
        self.assertEqual(main_images.first().name, 'Second Main')
        
        # Verify first image was demoted
        secondary_images = self.event.resources.filter(tag='LANDING_PHOTO_SECONDARY')
        self.assertEqual(secondary_images.count(), 1)
    
    def test_add_landing_image_without_file(self):
        """Test that image file is required"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'name': 'No Image',
            'is_main': 'true'
        }
        
        response = self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data,
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('image', response.data['detail'].lower())
    
    def test_list_landing_images(self):
        """Test listing all landing images for an event"""
        self.client.force_authenticate(user=self.user)
        
        # Add main image
        data1 = {
            'name': 'Main Image',
            'image': self._create_test_image(),
            'is_main': 'true',
            'public': 'true'
        }
        self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data1,
            format='multipart'
        )
        
        # Add secondary image
        data2 = {
            'name': 'Secondary Image',
            'image': self._create_test_image(),
            'is_main': 'false',
            'public': 'true'
        }
        self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data2,
            format='multipart'
        )
        
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/landing-images/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 2)
    
    def test_event_detail_includes_landing_images(self):
        """Test that event detail includes landing image fields"""
        self.client.force_authenticate(user=self.user)
        
        # Add a landing image
        data = {
            'name': 'Event Banner',
            'image': self._create_test_image(),
            'is_main': 'true',
            'public': 'true'
        }
        self.client.post(
            f'/api/event/list/{self.event.url_safe_title}/add-landing-image/',
            data,
            format='multipart'
        )
        
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('landing_images', response.data)
        self.assertIn('main_landing_image', response.data)
        self.assertIsNotNone(response.data['main_landing_image'])


class EventVenueAPITest(BaseEventAPITestCase):
    def setUp(self):
        super().setUp()
        
        # Create test POI and Venue
        self.poi = POI.objects.create(
            name='Test Conference Center',
            address='123 Main Street',
            postcode='SW1A 1AA',
            city='London',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        
        self.venue = Venue.objects.create(
            poi=self.poi,
            description='A modern conference center',
            capacity=500,
            added_by=self.user
        )
        
        # Create another venue for testing
        self.poi2 = POI.objects.create(
            name='Secondary Venue',
            address='456 High Street',
            postcode='SW1A 2BB',
            city='Manchester',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        
        self.venue2 = Venue.objects.create(
            poi=self.poi2,
            description='Another great venue',
            capacity=300,
            added_by=self.user
        )
        
        # Create an EventVenue association
        self.event_venue = EventVenue.objects.create(
            event=self.event,
            venue=self.venue
        )
    
    def test_list_event_venues_unauthenticated(self):
        """Test that unauthenticated users can list event venues"""
        response = self.client.get('/api/event/venues/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_event_venues_authenticated(self):
        """Test that authenticated users can list event venues"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/event/venues/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_event_venue(self):
        """Test retrieving a specific event venue"""
        response = self.client.get(f'/api/event/venues/{self.event_venue.event_venue_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['venue_name'], 'Test Conference Center')
        self.assertEqual(response.data['venue_city'], 'London')
        self.assertEqual(response.data['event_title'], 'Test Conference 2025')
    
    def test_retrieve_event_venue_has_hateoas_links(self):
        """Test that event venue includes HATEOAS links"""
        response = self.client.get(f'/api/event/venues/{self.event_venue.event_venue_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('event', response.data['_links'])
        self.assertIn('venue', response.data['_links'])
    
    def test_create_event_venue_authenticated(self):
        """Test creating an event-venue association"""
        self.client.force_authenticate(user=self.user)
        data = {
            'event': self.event.event_id,
            'venue': self.venue2.id
        }
        response = self.client.post('/api/event/venues/', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['venue_name'], 'Secondary Venue')
        self.assertEqual(response.data['event_title'], 'Test Conference 2025')
        
        # Verify it was actually created
        self.assertTrue(
            EventVenue.objects.filter(
                event=self.event,
                venue=self.venue2
            ).exists()
        )
    
    def test_create_event_venue_unauthenticated(self):
        """Test that unauthenticated users cannot create event venues"""
        data = {
            'event': self.event.event_id,
            'venue': self.venue2.id
        }
        response = self.client.post('/api/event/venues/', data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_filter_event_venues_by_event(self):
        """Test filtering event venues by event"""
        response = self.client.get(f'/api/event/venues/?event={self.event.url_safe_title}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        for result in response.data['results']:
            self.assertEqual(result['event_title'], 'Test Conference 2025')
    
    def test_filter_event_venues_by_venue(self):
        """Test filtering event venues by venue"""
        response = self.client.get(f'/api/event/venues/?venue={self.venue.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        for result in response.data['results']:
            self.assertEqual(result['venue_name'], 'Test Conference Center')
    
    def test_search_event_venues_by_venue_name(self):
        """Test searching event venues by venue name"""
        response = self.client.get('/api/event/venues/?search=Conference')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_search_event_venues_by_event_title(self):
        """Test searching event venues by event title"""
        response = self.client.get('/api/event/venues/?search=Test Conference')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_search_event_venues_by_city(self):
        """Test searching event venues by city"""
        response = self.client.get('/api/event/venues/?search=London')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        for result in response.data['results']:
            self.assertEqual(result['venue_city'], 'London')
    
    def test_delete_event_venue_authenticated(self):
        """Test deleting an event-venue association"""
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f'/api/event/venues/{self.event_venue.event_venue_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify it was actually deleted
        self.assertFalse(
            EventVenue.objects.filter(
                event_venue_id=self.event_venue.event_venue_id
            ).exists()
        )
    
    def test_delete_event_venue_unauthenticated(self):
        """Test that unauthenticated users cannot delete event venues"""
        response = self.client.delete(f'/api/event/venues/{self.event_venue.event_venue_id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_update_event_venue_authenticated(self):
        """Test updating an event-venue association"""
        self.client.force_authenticate(user=self.user)
        data = {
            'event': self.event.event_id,
            'venue': self.venue2.id
        }
        response = self.client.put(
            f'/api/event/venues/{self.event_venue.event_venue_id}/',
            data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['venue_name'], 'Secondary Venue')
        
        # Verify the update
        self.event_venue.refresh_from_db()
        self.assertEqual(self.event_venue.venue.id, self.venue2.id)
    
    def test_partial_update_event_venue_authenticated(self):
        """Test partially updating an event-venue association"""
        self.client.force_authenticate(user=self.user)
        data = {
            'venue': self.venue2.id
        }
        response = self.client.patch(
            f'/api/event/venues/{self.event_venue.event_venue_id}/',
            data
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['venue_name'], 'Secondary Venue')
    
    def test_event_venue_ordering_by_event_start_date(self):
        """Test that event venues are ordered by event start date by default"""
        # Create another event with an earlier start date
        earlier_event = Event.objects.create(
            title='Earlier Event',
            display_code='EE2024',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=12),
            organisation=self.organisation,
            status=EventStatusChoices.PUBLISHED
        )
        
        EventVenue.objects.create(
            event=earlier_event,
            venue=self.venue2
        )
        
        response = self.client.get('/api/event/venues/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # The first result should be the event with the later start date (descending order)
        if len(response.data['results']) >= 2:
            first_event = response.data['results'][0]['event_title']
            self.assertEqual(first_event, 'Test Conference 2025')
    
    def test_create_duplicate_event_venue(self):
        """Test that creating a duplicate event-venue association works (no unique constraint)"""
        self.client.force_authenticate(user=self.user)
        data = {
            'event': self.event.event_id,
            'venue': self.venue.id
        }
        response = self.client.post('/api/event/venues/', data)
        # This should succeed as there's no unique constraint on event-venue pairs
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

from apps.organisations.models import UserOrganisationMembership

class EventStaffInviteAPITest(BaseEventAPITestCase):
    """Test cases for EventStaffInvite API endpoints"""
    
    def setUp(self):
        """Set up test data for staff invite tests"""
        super().setUp()
        
        self.target_user = User.objects.create_user(
            username='targetuser',
            email='targetuser@example.com',
            password='testpass123'
        )
        
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='otheruser@example.com',
            password='testpass123'
        )
        
        # Make the main user an event staff member so they can create invites
        self.staff_member = EventStaff.objects.create(
            event=self.event,
            user=self.user,
            assigned_by=self.user
        )
        
        self.invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.target_user,
            invited_by=self.user,
            expires_at=timezone.now() + timedelta(days=7)
        )

        UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.target_user,
        )

        UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.other_user,
        )
    
    def test_list_staff_invites_authenticated(self):
        """Test listing staff invites as authenticated user"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_staff_invites_unauthenticated(self):
        """Test that unauthenticated users cannot list invites"""
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_retrieve_staff_invite(self):
        """Test retrieving a specific staff invite"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['target_user_email'], 'targetuser@example.com')
        self.assertEqual(response.data['event_title'], self.event.title)
        self.assertTrue(response.data['is_valid'])
    
    def test_retrieve_staff_invite_has_hateoas_links(self):
        """Test that staff invite includes HATEOAS links"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('event', response.data['_links'])
        self.assertIn('accept', response.data['_links'])
    
    def test_create_staff_invite_as_event_creator(self):
        """Test that event creator can create invites"""
        self.client.force_authenticate(user=self.user)
        data = {
            'target_user': self.other_user.id,
            'expires_at': (timezone.now() + timedelta(days=14)).isoformat()
        }
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['target_user'], self.other_user.id)
    
    def test_create_staff_invite_as_event_staff(self):
        """Test that event staff can create invites"""
        # Create another staff member
        staff_user = User.objects.create_user(
            username='staffuser2',
            email='staff2@example.com',
            password='testpass123'
        )

        # invite user
        
        EventStaff.objects.create(
            event=self.event,
            user=staff_user,
            assigned_by=self.user
        )
        
        self.client.force_authenticate(user=staff_user)
        data = {
            'target_user': self.other_user.id,
            'expires_at': (timezone.now() + timedelta(days=14)).isoformat()
        }
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_create_staff_invite_unauthorized(self):
        """Test that non-staff users cannot create invites"""
        self.client.force_authenticate(user=self.other_user)
        data = {
            'target_user': self.target_user.id,
            'expires_at': (timezone.now() + timedelta(days=14)).isoformat()
        }
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_create_duplicate_staff_invite_fails(self):
        """Test that creating duplicate invite fails"""
        self.client.force_authenticate(user=self.user)
        data = {
            'target_user': self.target_user.id
        }
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_create_staff_invite_for_existing_staff_fails(self):
        """Test that creating invite for existing staff member fails"""
        # Make target_user a staff member
        EventStaff.objects.create(
            event=self.event,
            user=self.other_user,
            assigned_by=self.user
        )
        
        self.client.force_authenticate(user=self.user)
        data = {
            'target_user': self.other_user.id
        }
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_update_staff_invite(self):
        """Test updating a staff invite"""
        self.client.force_authenticate(user=self.user)
        new_expires = (timezone.now() + timedelta(days=30)).isoformat()
        data = {
            'target_user': self.target_user.id,
            'expires_at': new_expires
        }
        response = self.client.put(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_partial_update_staff_invite(self):
        """Test partially updating a staff invite"""
        self.client.force_authenticate(user=self.user)
        data = {
            'expires_at': (timezone.now() + timedelta(days=30)).isoformat()
        }
        response = self.client.patch(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_delete_staff_invite_soft_deletes(self):
        """Test that deleting an invite marks it as inactive (soft delete)"""
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify invite is still in database but inactive
        self.invite.refresh_from_db()
        self.assertFalse(self.invite.is_active)
        self.assertFalse(self.invite.is_valid)
    
    def test_accept_invite_as_target_user(self):
        """Test that target user can accept their invite"""
        self.client.force_authenticate(user=self.target_user)
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/accept/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)
        self.assertIn('staff', response.data)
        
        # Verify invite is accepted
        self.invite.refresh_from_db()
        self.assertTrue(self.invite.accepted)
        self.assertIsNotNone(self.invite.accepted_at)
        self.assertFalse(self.invite.is_active)
        
        # Verify EventStaff was created
        staff = EventStaff.objects.filter(
            event=self.event,
            user=self.target_user
        ).first()
        self.assertIsNotNone(staff)
    
    def test_accept_invite_as_non_target_user_fails(self):
        """Test that non-target user cannot accept invite"""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/accept/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_accept_invalid_invite_fails(self):
        """Test that accepting invalid invite fails"""
        # Make invite inactive
        self.invite.is_active = False
        self.invite.save()
        
        self.client.force_authenticate(user=self.target_user)
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/accept/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    
    def test_accept_expired_invite_fails(self):
        """Test that accepting expired invite fails"""
        self.invite.expires_at = timezone.now() - timedelta(days=1)
        self.invite.save()
        
        self.client.force_authenticate(user=self.target_user)
        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/accept/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/accept/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_my_invites_action(self):
        """Test getting all invites sent to authenticated user"""
        # Create another invite for target_user
        other_event = Event.objects.create(
            title='Another Event',
            display_code='AE2025',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=40),
            end_datetime=timezone.now() + timedelta(days=42),
            organisation=self.organisation
        )
        EventStaffInvite.objects.create(
            event=other_event,
            target_user=self.target_user,
            invited_by=self.user
        )
        
        self.client.force_authenticate(user=self.target_user)
        # Get all invites for the specific event
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should see only invites for this event where they are target user
        self.assertEqual(len(response.data['results']), 1)
    
    def test_filter_invites_by_event(self):
        """Test that invites are automatically filtered by event from URL"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # All invites should be for this event
        for invite in response.data['results']:
            self.assertEqual(invite['event_title'], self.event.title)
    
    def test_filter_invites_by_target_user(self):
        """Test filtering invites by target user"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/?target_user={self.target_user.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for invite in response.data['results']:
            self.assertEqual(invite['target_user_email'], self.target_user.email)
    
    def test_filter_invites_by_accepted_status(self):
        """Test filtering invites by accepted status"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/?accepted=false')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for invite in response.data['results']:
            self.assertFalse(invite['accepted'])
    
    def test_filter_invites_by_validity(self):
        """Test filtering invites by is_valid parameter"""
        # Create an expired invite
        expired_invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.other_user,
            invited_by=self.user,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/?is_valid=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # All returned invites should be valid
        for invite in response.data['results']:
            self.assertTrue(invite['is_valid'])
    
    def test_search_invites_by_email(self):
        """Test searching invites by user email"""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/?search=targetuser')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    
    def test_target_user_can_view_own_invite(self):
        """Test that target user can view their own invite"""
        self.client.force_authenticate(user=self.target_user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_unrelated_user_cannot_view_invite(self):
        """Test that unrelated user cannot view invite"""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/{self.invite.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_invite_ordering(self):
        """Test that invites are ordered by added_at descending"""
        # Create another invite
        newer_invite = EventStaffInvite.objects.create(
            event=self.event,
            target_user=self.other_user,
            invited_by=self.user
        )
        
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/event/list/{self.event.url_safe_title}/staff-invites/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # First result should be the newer invite
        if len(response.data['results']) >= 2:
            first_invite_id = response.data['results'][0]['id']
            self.assertEqual(str(first_invite_id), str(newer_invite.id))


