"""
Comprehensive API tests for the attendee app.

Tests all endpoints, permissions, serialization, filtering, nested routing,
and business logic for attendees and related resources.

Author: AMDG Platform Team
Version: 1.0.0
"""
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from datetime import date, timedelta
import uuid
from djmoney.money import Money

from apps.attendee.models import (
    Attendee, AttendeeGuardian, AttendeeAction, AttendeeActionChoices,
    AttendeeRelationship, DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    EmergencyContact, Consent, AttendeeConsent,
    FamilyGroup, FamilyAttendee, AttendeeMessage, AttendeeMessagePriority,
    EventAttendance, AttendeeOrganisation, HumanRelationshipChoices
)
from apps.events.models import Event, EventType, EventStatusChoices, EventStaff
from apps.bookings.models import Booking, BookingPackage, TicketType, Ticket
from apps.organisations.models import Organisation
from apps.common.models import VerificationStatus
from apps.payments.models import (
    Payment,
    PaymentStatusChoices,
    PaymentMethod,
    PaymentMethodTypeChoices,
    RefundRequest,
    Donation,
    Discount,
    DiscountType,
)

User = get_user_model()


class AttendeeAPITestCase(APITestCase):
    """Base test case with common fixtures for attendee tests."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create users
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            is_staff=True,
            is_superuser=True
        )
        
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123',
            first_name='John',
            last_name='Doe'
        )
        
        self.other_user = User.objects.create_user(
            username='other',
            email='other@test.com',
            password='testpass123'
        )
        
        # Create organisation
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            created_by=self.admin_user
        )
        
        # Create event
        event_type = EventType.objects.create(
            title='Youth Camp',
            code='YCAMP'
        )
        self.event = Event.objects.create(
            title='Summer Camp 2026',
            display_code='SC2026',
            created_by=self.admin_user,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=37),
            status=EventStatusChoices.PUBLISHED,
            organisation=self.organisation
        )
        
        # Add regular user as event staff so they can access attendees
        EventStaff.objects.create(
            event=self.event,
            user=self.regular_user
        )
        
        # Create attendee
        self.attendee = Attendee.objects.create(
            user=self.regular_user,
            first_name='John',
            last_name='Doe',
            email='john.doe@test.com',
            phone_number='+447123456789',
            date_of_birth=date(2000, 1, 1),
            gender='Male',
            relationship_to_user=AttendeeRelationship.SELF,
            event=self.event,
            defined_by=self.regular_user
        )
        
        # Create child attendee with guardian
        self.child_attendee = Attendee.objects.create(
            first_name='Jane',
            last_name='Doe',
            email='jane.doe@test.com',
            date_of_birth=date(2015, 5, 10),
            gender='Female',
            relationship_to_user=AttendeeRelationship.CHILD,
            event=self.event,
            defined_by=self.regular_user
        )
        
        AttendeeGuardian.objects.create(
            user=self.regular_user,
            attendee=self.child_attendee,
            relationship=AttendeeRelationship.PARRENT
        )
        
        # Create reference data
        self.dietary_requirement = DietaryRequirement.objects.create(
            code='VEGAN',
            label='Vegan',
            description='No animal products',
            verification_status=VerificationStatus.VERIFIED
        )
        
        self.medical_condition = MedicalCondition.objects.create(
            code='ASTHMA',
            label='Asthma',
            description='Respiratory condition',
            verification_status=VerificationStatus.VERIFIED
        )
        
        self.accessibility_requirement = AccessibilityRequirement.objects.create(
            code='WHEELCHAIR',
            label='Wheelchair Access',
            description='Requires wheelchair accessibility',
            verification_status=VerificationStatus.VERIFIED
        )
        
        self.consent = Consent.objects.create(
            code='PHOTO',
            title='Photo Consent',
            description='Permission to take photos',
            event=self.event
        )
        
        self.client = APIClient()


class AttendeeEndpointTests(AttendeeAPITestCase):
    """Test attendee list/create/retrieve/update/delete endpoints."""
    
    def test_list_attendees_unauthenticated(self):
        """Unauthenticated users cannot list attendees."""
        response = self.client.get('/api/attendees/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_list_attendees_as_user(self):
        """User should see their own attendees and guarded attendees."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/attendees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)  # self and child
    
    def test_list_attendees_as_admin(self):
        """Admin should see all attendees."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_retrieve_attendee_by_uuid(self):
        """Test retrieving attendee by attendee_id (UUID)."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/attendees/{self.attendee.attendee_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['first_name'], 'John')
        self.assertEqual(response.data['last_name'], 'Doe')
        self.assertIn('age', response.data)
        self.assertIn('is_minor', response.data)
        self.assertIn('_links', response.data)
    
    def test_create_attendee(self):
        """Test creating a new attendee."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'first_name': 'Alice',
            'last_name': 'Smith',
            'email': 'alice@test.com',
            'phone_number': '+447987654321',
            'date_of_birth': '1995-03-15',
            'gender': 'Female',
            'relationship_to_user': AttendeeRelationship.SELF,
            'event': self.event.id
        }
        response = self.client.post('/api/attendees/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['first_name'], 'Alice')
        self.assertTrue(response.data['attendee_id'])
    
    def test_update_attendee(self):
        """Test updating attendee information."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'phone_number': '+447000000000'
        }
        response = self.client.patch(
            f'/api/attendees/{self.attendee.attendee_id}/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['phone_number'], '+447000000000')
    
    def test_delete_attendee_soft_delete(self):
        """Test soft deleting an attendee."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.delete(f'/api/attendees/{self.attendee.attendee_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify soft delete
        self.attendee.refresh_from_db()
        self.assertIsNotNone(self.attendee.deleted_at)
    
    def test_other_user_cannot_access_attendee(self):
        """Other users cannot access attendees they don't own."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(f'/api/attendees/{self.attendee.attendee_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AttendeeFilteringTests(AttendeeAPITestCase):
    """Test attendee filtering and search capabilities."""
    
    def test_search_attendees_by_name(self):
        """Test searching attendees by name."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/attendees/?search=John')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_by_event(self):
        """Test filtering attendees by event."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/attendees/?event={self.event.url_safe_title}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_filter_by_age_range(self):
        """Test filtering by age range."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?age_min=18&age_max=30')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for attendee in response.data['results']:
            self.assertGreaterEqual(attendee['age'], 18)
            self.assertLessEqual(attendee['age'], 30)
    
    def test_filter_minors(self):
        """Test filtering minor attendees."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?is_minor=true')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for attendee in response.data['results']:
            self.assertTrue(attendee['is_minor'])
    
    def test_filter_by_relationship(self):
        """Test filtering by relationship to user."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/attendees/?relationship_to_user={AttendeeRelationship.SELF}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class AttendeePaymentFilteringTests(AttendeeAPITestCase):
    """Test attendee filtering by payment, refund, donation, and discount context."""

    def setUp(self):
        super().setUp()

        self.booking = Booking.objects.create(
            event=self.event,
            made_by=self.regular_user,
        )
        self.attendee.booking = self.booking
        self.attendee.save(update_fields=['booking'])

        self.ticket_type = TicketType.objects.create(
            event=self.event,
            title='General Admission',
            created_by=self.admin_user,
        )
        self.booking_package = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(75, 'GBP'),
            created_by=self.admin_user,
        )

        self.payment_method = PaymentMethod.objects.create(
            title='Main Bank Transfer',
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            created_by=self.admin_user,
        )

        booking_ct = ContentType.objects.get_for_model(Booking)
        self.booking_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.COMPLETED,
            target_type=booking_ct,
            target_id=self.booking.id,
            bank_transfer_reference='BANKREF0001',
        )

        self.ticket_payment = Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(75, 'GBP'),
            status=PaymentStatusChoices.PENDING,
        )

        self.ticket = Ticket.objects.create(
            ticket_type=self.ticket_type,
            attendee=self.attendee,
            package=self.booking_package,
            payment=self.ticket_payment,
        )

        self.refund_request = RefundRequest.objects.create(
            payment=self.booking_payment,
            amount=Money(25, 'GBP'),
            reason='Participant cannot attend event',
            requested_by=self.regular_user,
            is_active=True,
        )

        self.donation = Donation.objects.create(
            amount=Money(10, 'GBP'),
            donated_by=self.regular_user,
            payment=self.booking_payment,
        )

        booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
        self.discount = Discount.objects.create(
            name='Early Bird Saver',
            discount_type=DiscountType.PERCENTAGE,
            percentage=10,
            target_type=booking_package_ct,
            target_id=self.booking_package.id,
            active=True,
            created_by=self.admin_user,
        )

    def _assert_only_primary_attendee(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['attendee_id'], str(self.attendee.attendee_id))

    def test_filter_by_payment_id(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/attendees/?payment_id={self.booking_payment.payment_id}')
        self._assert_only_primary_attendee(response)

    def test_filter_by_payment_status_defaults_to_booking_payments(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?payment_status=PENDING')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(len(response.data['results']), 0)

    def test_filter_by_payment_status_matches_pending_booking_payments(self):
        booking_ct = ContentType.objects.get_for_model(Booking)
        Payment.objects.create(
            user=self.regular_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(100, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            target_type=booking_ct,
            target_id=self.booking.id,
        )

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?payment_status=PENDING')
        self._assert_only_primary_attendee(response)

    def test_filter_by_payment_status_with_ticket_target_still_works(self):
        self.client.force_authenticate(user=self.admin_user)
        Payment.objects.create(
            user=self.other_user,
            event=self.event,
            method=self.payment_method,
            base_amount=Money(75, 'GBP'),
            status=PaymentStatusChoices.PENDING,
            target_type=ContentType.objects.get_for_model(Ticket),
            target_id=self.ticket.ticket_id,
        )
     
        response = self.client.get('/api/attendees/?payment_status=PENDING&payment_target=ticket')
        self._assert_only_primary_attendee(response)

    def test_filter_by_payment_reference(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/attendees/?payment_reference={self.booking_payment.payment_reference}')
        self._assert_only_primary_attendee(response)

    def test_filter_by_bank_transfer_reference(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?bank_transfer_reference=BANKREF0001')
        self._assert_only_primary_attendee(response)

    def test_filter_by_payment_target(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?payment_target=booking')
        self._assert_only_primary_attendee(response)

    def test_filter_by_payment_method_type_and_title(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            '/api/attendees/?payment_method_type=BANK_TRANSFER&payment_method_title=Main Bank'
        )
        self._assert_only_primary_attendee(response)

    def test_filter_by_refund_status_and_active(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(
            f'/api/attendees/?refund_status={VerificationStatus.PENDING}&refund_is_active=true'
        )
        self._assert_only_primary_attendee(response)

    def test_filter_by_donation_status(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(f'/api/attendees/?donation_status={VerificationStatus.PENDING}')
        self._assert_only_primary_attendee(response)

    def test_filter_by_discount_name(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/attendees/?discount_name=Early Bird')
        self._assert_only_primary_attendee(response)


class NestedResourceTests(AttendeeAPITestCase):
    """Test nested resource endpoints under attendees."""
    
    def test_list_dietary_requirements_for_attendee(self):
        """Test listing dietary requirements for specific attendee."""
        # Create dietary requirement for attendee
        AttendeeDietaryRequirement.objects.create(
            attendee=self.attendee,
            dietary_requirement=self.dietary_requirement,
            notes='Strict vegan',
            verification_status=VerificationStatus.VERIFIED
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/attendees/{self.attendee.attendee_id}/dietary-requirements/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['notes'], 'Strict vegan')
    
    def test_create_dietary_requirement_for_attendee(self):
        """Test adding dietary requirement to attendee."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'dietary_requirement': self.dietary_requirement.id,
            'notes': 'Very strict',
            'verification_status': VerificationStatus.VERIFIED
        }
        response = self.client.post(
            f'/api/attendees/{self.attendee.attendee_id}/dietary-requirements/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['notes'], 'Very strict')
    
    def test_list_medical_conditions_for_attendee(self):
        """Test listing medical conditions for specific attendee."""
        AttendeeMedicalCondition.objects.create(
            attendee=self.attendee,
            medical_condition=self.medical_condition,
            severity='Moderate',
            notes='Needs inhaler',
            verification_status=VerificationStatus.VERIFIED
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/attendees/{self.attendee.attendee_id}/medical-conditions/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['severity'], 'Moderate')
    
    def test_create_emergency_contact_for_attendee(self):
        """Test creating emergency contact for attendee."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'first_name': 'Mary',
            'last_name': 'Doe',
            'relationship': HumanRelationshipChoices.PARENT,
            'phone_number': '+447111222333',
            'email': 'mary@test.com',
            'primary_contact': True,
            'verification_status': VerificationStatus.VERIFIED
        }
        response = self.client.post(
            f'/api/attendees/{self.attendee.attendee_id}/emergency-contacts/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['first_name'], 'Mary')
        self.assertTrue(response.data['primary_contact'])
    
    def test_create_consent_for_attendee(self):
        """Test recording consent for attendee."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'consent': self.consent.id,
            'consent_given': True,
            'given_at': timezone.now().isoformat()
        }
        response = self.client.post(
            f'/api/attendees/{self.attendee.attendee_id}/consents/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['consent_given'])
    
    def test_nested_resource_filtered_by_attendee(self):
        """Test that nested resources are filtered by parent attendee."""
        # Create dietary req for another attendee
        other_attendee = Attendee.objects.create(
            user=self.other_user,
            first_name='Bob',
            last_name='Smith',
            date_of_birth=date(1990, 1, 1),
            event=self.event
        )
        AttendeeDietaryRequirement.objects.create(
            attendee=other_attendee,
            dietary_requirement=self.dietary_requirement
        )
        
        # Should not see other attendee's requirements
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/attendees/{self.attendee.attendee_id}/dietary-requirements/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)


class GuardianTests(AttendeeAPITestCase):
    """Test guardian relationship endpoints."""
    
    def test_list_guardians(self):
        """Test listing guardian relationships."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/guardians/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_create_guardian_relationship(self):
        """Test creating a guardian relationship."""
        # Create a new child attendee for this test
        new_child = Attendee.objects.create(
            first_name='Tommy',
            last_name='Smith',
            date_of_birth=date(2016, 3, 15),
            relationship_to_user=AttendeeRelationship.CHILD,
            event=self.event,
            defined_by=self.regular_user
        )
        
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'user': self.other_user.id,
            'attendee': new_child.attendee_id,
            'relationship': AttendeeRelationship.PARRENT
        }
        response = self.client.post('/api/guardians/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class ReferenceDataTests(AttendeeAPITestCase):
    """Test reference data endpoints (dietary, medical, accessibility, consent)."""
    
    def test_list_dietary_requirements(self):
        """Test listing all dietary requirement types."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/dietary-requirements/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_medical_conditions(self):
        """Test listing all medical condition types."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/medical-conditions/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_accessibility_requirements(self):
        """Test listing all accessibility requirement types."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/accessibility-requirements/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_create_dietary_requirement_as_staff(self):
        """Test creating new dietary requirement type as staff."""
        self.client.force_authenticate(user=self.admin_user)
        data = {
            'code': 'GLUTENFREE',
            'label': 'Gluten Free',
            'description': 'No gluten',
            'verification_status': VerificationStatus.VERIFIED
        }
        response = self.client.post('/api/dietary-requirements/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['code'], 'GLUTENFREE')
    
    def test_create_reference_data_as_regular_user_fails(self):
        """Regular users cannot create reference data."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'code': 'TEST',
            'label': 'Test',
            'verification_status': VerificationStatus.VERIFIED
        }
        response = self.client.post('/api/dietary-requirements/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FamilyGroupTests(AttendeeAPITestCase):
    """Test family group endpoints."""
    
    def test_create_family_group(self):
        """Test creating a family group."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'family_name': 'Doe Family',
            'primary_contact': self.regular_user.id,
            'event': self.event.pk
        }
        response = self.client.post('/api/family-groups/', data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['family_name'], 'Doe Family')
    
    def test_add_attendee_to_family(self):
        """Test adding attendee to family group."""
        family = FamilyGroup.objects.create(
            family_name='Doe Family',
        )
        
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'family_group': family.id,
            'attendee': self.attendee.attendee_id,
            'relationship': HumanRelationshipChoices.PARENT
        }
        response = self.client.post('/api/family-attendees/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class AttendeeMessageTests(AttendeeAPITestCase):
    """Test attendee message endpoints."""
    
    def test_create_message(self):
        """Test creating an attendee message."""
        self.client.force_authenticate(user=self.regular_user)
        data = {
            'attendee': self.attendee.id,
            'subject': 'Question about event',
            'message': 'What time does it start?',
            'priority': AttendeeMessagePriority.MEDIUM
        }
        response = self.client.post('/api/messages/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['subject'], 'Question about event')
    
    def test_list_messages_as_owner(self):
        """User can see their own messages."""
        AttendeeMessage.objects.create(
            attendee=self.attendee,
            subject='Test',
            message='Test message',
            priority=AttendeeMessagePriority.MEDIUM
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/messages/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class SoftDeleteTests(AttendeeAPITestCase):
    """Test soft delete functionality."""
    
    def test_soft_deleted_attendees_excluded_by_default(self):
        """Soft deleted attendees should not appear in list by default."""
        # Soft delete attendee
        self.attendee.deleted_at = timezone.now()
        self.attendee.deleted_by = self.regular_user
        self.attendee.save()
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/attendees/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see child_attendee, not soft-deleted attendee
        attendee_ids = [a['attendee_id'] for a in response.data['results']]
        self.assertNotIn(str(self.attendee.attendee_id), attendee_ids)


class HATEOASTests(AttendeeAPITestCase):
    """Test HATEOAS links in responses."""
    
    def test_attendee_has_links(self):
        """Attendee response should include _links."""
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(f'/api/attendees/{self.attendee.attendee_id}/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('dietary_requirements', response.data['_links'])
        self.assertIn('medical_conditions', response.data['_links'])
    
    def test_nested_resource_has_links(self):
        """Nested resources should have HATEOAS links."""
        dietary_req = AttendeeDietaryRequirement.objects.create(
            attendee=self.attendee,
            dietary_requirement=self.dietary_requirement
        )
        
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(
            f'/api/attendees/{self.attendee.attendee_id}/dietary-requirements/'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data['results'][0])
