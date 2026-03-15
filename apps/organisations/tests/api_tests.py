"""
API Tests for Organisation endpoints.

Tests cover the complete API workflow for organisation management:
1. Organisation CRUD with permissions
2. Organisation contacts management
3. Organisation control assignments
4. User membership with verification workflows
5. Acceptance codes management
6. Invites with accept action
7. Event involvement
8. Sponsorship with packages
9. Leadership management
10. HATEOAS link validation
11. Filtering and search
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    UserOrganisationMembership, OrganisationInvite, OrganisationAcceptanceCode,
    InvolvedEventOrganisation, InvolvedOrganisationRoleChoices,
    EventSponsor, EventSponsorPackage, Leader
)
from apps.events.models import Event, EventType, EventRole, EventRoleAssignment, EventRoleCategoryChoices

User = get_user_model()


class OrganisationAPITest(TestCase):
    """Test Organisation API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create users
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.regular_user = User.objects.create_user(
            email='user@example.com',
            password='userpass123'
        )
        
        # Create organisation
        self.organisation = Organisation.objects.create(
            title='St. Mary\'s Parish',
            description='Catholic community',
            created_by=self.admin_user
        )
        
        # Add controller
        OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller_user,
            added_by=self.admin_user
        )
    
    def test_list_organisations_unauthenticated(self):
        """Test listing organisations without authentication."""
        url = reverse('organisations:organisation-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_list_organisations_authenticated(self):
        """Test listing organisations with authentication."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('organisations:organisation-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
    
    def test_retrieve_organisation_detail(self):
        """Test retrieving organisation details."""
        url = reverse('organisations:organisation-detail', kwargs={'pk': self.organisation.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'St. Mary\'s Parish')
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('contacts', response.data['_links'])
        self.assertIn('memberships', response.data['_links'])
    
    def test_create_organisation_authenticated(self):
        """Test creating an organisation."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('organisations:organisation-list')
        data = {
            'title': 'Holy Trinity Church',
            'description': 'New parish community',
            'external_website': 'https://www.holytrinityexample.org'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Organisation.objects.count(), 2)
        new_org = Organisation.objects.get(title='Holy Trinity Church')
        self.assertEqual(new_org.created_by, self.regular_user)
    
    def test_create_organisation_duplicate_title(self):
        """Test creating organisation with duplicate title fails."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('organisations:organisation-list')
        data = {
            'title': 'St. Mary\'s Parish',  # Duplicate
            'description': 'Duplicate'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_update_organisation_as_controller(self):
        """Test updating organisation as controller."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisation-detail', kwargs={'pk': self.organisation.id})
        data = {
            'title': 'St. Mary\'s Parish',
            'description': 'Updated description'
        }
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organisation.refresh_from_db()
        self.assertEqual(self.organisation.description, 'Updated description')
    
    def test_update_organisation_as_non_controller_fails(self):
        """Test updating organisation as non-controller fails."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('organisations:organisation-detail', kwargs={'pk': self.organisation.id})
        data = {'description': 'Unauthorized update'}
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_delete_organisation_as_controller(self):
        """Test deleting organisation as controller."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisation-detail', kwargs={'pk': self.organisation.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Organisation.objects.count(), 0)
    
    def test_organisation_contacts_nested_action(self):
        """Test accessing organisation contacts via nested action."""
        # Create some contacts
        OrganisationContact.objects.create(
            organisation=self.organisation,
            name='Father John',
            email='fr.john@parish.org'
        )
        
        url = reverse('organisations:organisation-contacts', kwargs={'pk': self.organisation.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Father John')
    
    def test_organisation_memberships_nested_action(self):
        """Test accessing organisation memberships via nested action."""
        UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.regular_user,
            added_by=self.admin_user
        )
        
        url = reverse('organisations:organisation-memberships', kwargs={'pk': self.organisation.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
    
    def test_filter_organisations_by_search(self):
        """Test filtering organisations by search."""
        Organisation.objects.create(
            title='Sacred Heart',
            description='Another parish',
            created_by=self.admin_user
        )
        
        url = reverse('organisations:organisation-list')
        response = self.client.get(url, {'search': 'mary'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['title'], 'St. Mary\'s Parish')


class OrganisationContactAPITest(TestCase):
    """Test OrganisationContact API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.admin_user
        )
        OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller_user,
            added_by=self.admin_user
        )
        self.contact = OrganisationContact.objects.create(
            organisation=self.organisation,
            name='Father Michael',
            email='fr.michael@parish.org',
            phone='+447123456789'
        )
    
    def test_list_contacts(self):
        """Test listing contacts."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontact-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
    
    def test_create_contact_as_controller(self):
        """Test creating contact as controller."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontact-list')
        data = {
            'organisation': self.organisation.id,
            'name': 'Sister Anne',
            'email': 's.anne@parish.org',
            'phone': '+447987654321',
            'label': 'Secretary'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(OrganisationContact.objects.count(), 2)
    
    def test_update_contact(self):
        """Test updating contact."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontact-detail', kwargs={'pk': self.contact.id})
        data = {'label': 'Parish Priest'}
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.label, 'Parish Priest')
    
    def test_delete_contact(self):
        """Test deleting contact."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontact-detail', kwargs={'pk': self.contact.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(OrganisationContact.objects.count(), 0)
    
    def test_filter_contacts_by_organisation(self):
        """Test filtering contacts by organisation."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontact-list')
        response = self.client.get(url, {'organisation': self.organisation.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


class OrganisationControlAPITest(TestCase):
    """Test OrganisationControl API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.new_controller = User.objects.create_user(
            email='newcontrol@parish.org',
            password='newcontrolpass'
        )
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.admin_user
        )
        self.control = OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller_user,
            added_by=self.admin_user
        )
    
    def test_list_controls(self):
        """Test listing organisation controls."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontrol-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_create_control_as_controller(self):
        """Test adding new controller."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontrol-list')
        data = {
            'organisation': self.organisation.id,
            'user': self.new_controller.id
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(OrganisationControl.objects.count(), 2)
    
    def test_create_duplicate_control_fails(self):
        """Test creating duplicate control fails."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontrol-list')
        data = {
            'organisation': self.organisation.id,
            'user': self.controller_user.id  # Already a controller
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_delete_control(self):
        """Test removing controller."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationcontrol-detail', kwargs={'pk': self.control.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class UserOrganisationMembershipAPITest(TestCase):
    """Test UserOrganisationMembership API endpoints with verification actions."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.member_user = User.objects.create_user(
            email='member@example.com',
            password='memberpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.admin_user,
            required_acceptance_code=True
        )
        OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller_user,
            added_by=self.admin_user
        )
    
    def test_list_memberships(self):
        """Test listing memberships."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationmembership-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_create_membership(self):
        """Test creating membership."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationmembership-list')
        data = {
            'organisation': self.organisation.id,
            'user': self.member_user.id
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        membership = UserOrganisationMembership.objects.get(user=self.member_user)
        self.assertEqual(membership.added_by, self.controller_user)
    
    def test_verify_membership_with_code(self):
        """Test verifying membership with acceptance code."""
        # Create membership
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.controller_user
        )
        
        # Create acceptance code
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            code='TESTCODE123',
            added_by=self.admin_user,
            max_uses=10
        )
        
        # Verify with code
        self.client.force_authenticate(user=self.member_user)
        url = reverse('organisations:organisationmembership-verify-with-code', kwargs={'pk': membership.id})
        data = {'code': 'TESTCODE123'}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership.refresh_from_db()
        self.assertIsNotNone(membership.verified_at)
        code.refresh_from_db()
        self.assertEqual(code.uses, 1)
    
    def test_verify_membership_with_invalid_code(self):
        """Test verifying with invalid code fails."""
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.controller_user
        )
        
        self.client.force_authenticate(user=self.member_user)
        url = reverse('organisations:organisationmembership-verify-with-code', kwargs={'pk': membership.id})
        data = {'code': 'WRONGCODE'}
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_verify_membership_manually(self):
        """Test manual membership verification."""
        self.organisation.requires_manual_verification = True
        self.organisation.save()
        
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.controller_user
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationmembership-verify-manually', kwargs={'pk': membership.id})
        response = self.client.post(url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        membership.refresh_from_db()
        self.assertIsNotNone(membership.verified_at)
    
    def test_filter_memberships_by_verification(self):
        """Test filtering memberships by verification status."""
        # Create verified membership
        verified_membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.controller_user,
            verified_at=timezone.now()
        )
        
        # Create unverified membership
        other_user = User.objects.create_user(email='other@example.com', password='pass')
        UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=other_user,
            added_by=self.controller_user
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationmembership-list')
        response = self.client.get(url, {'is_verified': 'true'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


class OrganisationInviteAPITest(TestCase):
    """Test OrganisationInvite API endpoints with accept action."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.invitee_user = User.objects.create_user(
            email='invitee@example.com',
            password='inviteepass123'
        )
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.admin_user
        )
        OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller_user,
            added_by=self.admin_user
        )
    
    def test_list_invites(self):
        """Test listing invites."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationinvite-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_create_invite(self):
        """Test creating an invite."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationinvite-list')
        data = {
            'organisation': self.organisation.id,
            'target_user': self.invitee_user.id,
            'expires_at': (timezone.now() + timedelta(days=7)).isoformat()
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        invite = OrganisationInvite.objects.get(target_user=self.invitee_user)
        self.assertEqual(invite.invited_by, self.controller_user)
        self.assertTrue(invite.is_valid)
    
    def test_accept_invite(self):
        """Test accepting an invite."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee_user,
            invited_by=self.controller_user,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.client.force_authenticate(user=self.invitee_user)
        url = reverse('organisations:organisationinvite-accept', kwargs={'pk': invite.id})
        response = self.client.post(url, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        invite.refresh_from_db()
        self.assertTrue(invite.accepted)
        self.assertIsNotNone(invite.accepted_at)
        
        # Check membership was created
        self.assertTrue(
            UserOrganisationMembership.objects.filter(
                organisation=self.organisation,
                user=self.invitee_user
            ).exists()
        )
    
    def test_accept_invite_wrong_user_fails(self):
        """Test accepting invite as wrong user fails."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee_user,
            invited_by=self.controller_user
        )
        
        # Try to accept as different user
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationinvite-accept', kwargs={'pk': invite.id})
        response = self.client.post(url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_create_duplicate_invite_fails(self):
        """Test creating duplicate invite fails."""
        OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee_user,
            invited_by=self.controller_user
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationinvite-list')
        data = {
            'organisation': self.organisation.id,
            'target_user': self.invitee_user.id
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_filter_invites_by_validity(self):
        """Test filtering invites by validity."""
        # Valid invite
        OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee_user,
            invited_by=self.controller_user,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        # Expired invite
        other_user = User.objects.create_user(email='other@example.com', password='pass')
        OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=other_user,
            invited_by=self.controller_user,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:organisationinvite-list')
        response = self.client.get(url, {'is_valid': 'true'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


class EventSponsorAPITest(TestCase):
    """Test EventSponsor and EventSponsorPackage API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        
        # Create event organisation
        self.event_org = Organisation.objects.create(
            title='Event Host',
            created_by=self.admin_user
        )
        
        # Create sponsor organisation
        self.sponsor_org = Organisation.objects.create(
            title='Sponsor Corp',
            created_by=self.admin_user
        )
        OrganisationControl.objects.create(
            organisation=self.sponsor_org,
            user=self.controller_user,
            added_by=self.admin_user
        )
        
        # Create event
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.admin_user
        )
        self.event = Event.objects.create(
            title='Annual Conference',
            display_code='AC2024',
            created_by=self.admin_user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.event_org
        )
        
        # Create event role for admin
        admin_role = EventRole.objects.create(
            name='Admin',
            code='ADMIN',
            category=EventRoleCategoryChoices.ADMINISTRATIVE,
        )
        EventRoleAssignment.objects.create(
            user=self.admin_user,
            event=self.event,
            role=admin_role
        )
    
    def test_list_sponsors(self):
        """Test listing event sponsors."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:eventsponsor-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_create_sponsor(self):
        """Test creating event sponsor."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:eventsponsor-list')
        data = {
            'name': 'Gold Sponsor',
            'description': 'Premium sponsor',
            'organisation_id': str(self.sponsor_org.organisation_id),
            'event_id': str(self.event.event_id)
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        sponsor = EventSponsor.objects.get(name='Gold Sponsor')
        self.assertEqual(sponsor.added_by, self.controller_user)
    
    def test_retrieve_sponsor_detail(self):
        """Test retrieving sponsor with packages."""
        sponsor = EventSponsor.objects.create(
            name='Platinum Sponsor',
            organisation=self.sponsor_org,
            event=self.event,
            added_by=self.admin_user
        )
        package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Platinum Package',
            base_amount=10000.00
        )
        sponsor.package = package
        sponsor.save(update_fields=['package'])
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:eventsponsor-detail', kwargs={'sponsor_id': sponsor.sponsor_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('package', response.data)
        self.assertIsNotNone(response.data['package'])
    
    def test_sponsor_packages_nested_action(self):
        """Test accessing sponsor packages via nested action."""
        sponsor = EventSponsor.objects.create(
            name='Silver Sponsor',
            organisation=self.sponsor_org,
            event=self.event,
            added_by=self.admin_user
        )
        package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Silver Package',
            base_amount=5000.00
        )
        sponsor.package = package
        sponsor.save(update_fields=['package'])
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:eventsponsor-packages', kwargs={'sponsor_id': sponsor.sponsor_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


class EventSponsorPackageAPITest(TestCase):
    """Test EventSponsorPackage API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        
        self.event_org = Organisation.objects.create(
            title='Event Host',
            created_by=self.admin_user
        )
        self.sponsor_org = Organisation.objects.create(
            title='Sponsor Corp',
            created_by=self.admin_user
        )
        
        self.event_type = EventType.objects.create(
            title='Festival',
            code='FEST',
            created_by=self.admin_user
        )
        self.event = Event.objects.create(
            title='Annual Festival',
            display_code='AF2024',
            created_by=self.admin_user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=62),
            organisation=self.event_org
        )
        
        self.sponsor = EventSponsor.objects.create(
            name='Main Sponsor',
            organisation=self.sponsor_org,
            event=self.event,
            added_by=self.admin_user
        )
    
    def test_create_sponsor_package(self):
        """Test creating sponsorship package."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:sponsorpackage-list')
        data = {
            'event_id': str(self.event.event_id),
            'package_name': 'Gold Package',
            'package_description': 'Premium benefits',
            'base_amount': 7500.00,
            'percentage_modifier': 0.00
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        package = EventSponsorPackage.objects.get(package_name='Gold Package')
        self.assertEqual(float(package.base_amount.amount), 7500.00)
    
    def test_package_with_percentage_modifier(self):
        """Test package with percentage modifier."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:sponsorpackage-list')
        data = {
            'event_id': str(self.event.event_id),
            'package_name': 'Early Bird',
            'base_amount': 5000.00,
            'percentage_modifier': -10.00  # 10% discount
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        package = EventSponsorPackage.objects.get(package_name='Early Bird')
        # Modified amount should be 4500 (5000 - 10%)
        self.assertEqual(float(package.modified_amount.amount), 4500.00)
    
    def test_package_detail_with_payment_info(self):
        """Test retrieving package with payment info."""
        package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Diamond Package',
            base_amount=15000.00
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:sponsorpackage-detail', kwargs={'package_id': package.package_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('has_payment', response.data)
        self.assertFalse(response.data['has_payment'])


class LeaderAPITest(TestCase):
    """Test Leader API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        self.controller_user = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.leader_user = User.objects.create_user(
            email='leader@parish.org',
            password='leaderpass123'
        )
        
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.admin_user
        )
        OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller_user,
            added_by=self.admin_user
        )
    
    def test_list_leaders(self):
        """Test listing leaders."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:leader-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_create_leader(self):
        """Test creating leader for organisation."""
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:leader-list')
        data = {
            'user': self.leader_user.id,
            'organisation': self.organisation.id,
            'notes': 'Youth ministry coordinator'
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify leader was created with correct generic FK
        from django.contrib.contenttypes.models import ContentType
        org_ct = ContentType.objects.get_for_model(Organisation)
        leader = Leader.objects.get(user=self.leader_user)
        self.assertEqual(leader.target_type, org_ct)
        self.assertEqual(leader.target_id, self.organisation.id)
        self.assertEqual(leader.authority_object, self.organisation)
    
    def test_create_duplicate_leader_fails(self):
        """Test creating duplicate leader fails."""
        from django.contrib.contenttypes.models import ContentType
        org_ct = ContentType.objects.get_for_model(Organisation)
        
        Leader.objects.create(
            user=self.leader_user,
            target_type=org_ct,
            target_id=self.organisation.id,
            added_by=self.controller_user
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:leader-list')
        data = {
            'user': self.leader_user.id,
            'organisation': self.organisation.id
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_update_leader_notes(self):
        """Test updating leader notes."""
        from django.contrib.contenttypes.models import ContentType
        org_ct = ContentType.objects.get_for_model(Organisation)
        
        leader = Leader.objects.create(
            user=self.leader_user,
            target_type=org_ct,
            target_id=self.organisation.id,
            added_by=self.controller_user
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:leader-detail', kwargs={'pk': leader.id})
        data = {'notes': 'Updated responsibilities', 'organisation': self.organisation.id}
        response = self.client.patch(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        leader.refresh_from_db()
        self.assertEqual(leader.notes, 'Updated responsibilities')
    
    def test_filter_leaders_by_organisation(self):
        """Test filtering leaders by organisation."""
        from django.contrib.contenttypes.models import ContentType
        org_ct = ContentType.objects.get_for_model(Organisation)
        
        Leader.objects.create(
            user=self.leader_user,
            target_type=org_ct,
            target_id=self.organisation.id,
            added_by=self.controller_user
        )
        
        # Create another org and leader
        other_org = Organisation.objects.create(
            title='Other Parish',
            created_by=self.admin_user
        )
        other_leader = User.objects.create_user(
            email='other@leader.org',
            password='pass'
        )
        Leader.objects.create(
            user=other_leader,
            target_type=org_ct,
            target_id=other_org.id,
            added_by=self.admin_user
        )
        
        self.client.force_authenticate(user=self.controller_user)
        url = reverse('organisations:leader-list')
        response = self.client.get(url, {'organisation': self.organisation.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)


class InvolvedEventOrganisationAPITest(TestCase):
    """Test InvolvedEventOrganisation API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123',
            is_staff=True
        )
        
        self.organisation = Organisation.objects.create(
            title='Community Org',
            created_by=self.admin_user
        )
        self.event_org = Organisation.objects.create(
            title='Event Host',
            created_by=self.admin_user
        )
        
        self.event_type = EventType.objects.create(
            title='Retreat',
            code='RET',
            created_by=self.admin_user
        )
        self.event = Event.objects.create(
            title='Youth Retreat',
            display_code='YR2024',
            created_by=self.admin_user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.event_org
        )
    
    def test_create_event_involvement(self):
        """Test creating organisation involvement in event."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:involvedeventorganisation-list')
        data = {
            'organisation': self.organisation.id,
            'event': self.event.id,
            'role': InvolvedOrganisationRoleChoices.PARTNER
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        involvement = InvolvedEventOrganisation.objects.get(
            organisation=self.organisation,
            event=self.event
        )
        self.assertEqual(involvement.role, InvolvedOrganisationRoleChoices.PARTNER)
    
    def test_filter_involvement_by_role(self):
        """Test filtering by role."""
        InvolvedEventOrganisation.objects.create(
            organisation=self.organisation,
            event=self.event,
            role=InvolvedOrganisationRoleChoices.ORGANISER,
            added_by=self.admin_user
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('organisations:involvedeventorganisation-list')
        response = self.client.get(url, {'role': InvolvedOrganisationRoleChoices.ORGANISER})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
