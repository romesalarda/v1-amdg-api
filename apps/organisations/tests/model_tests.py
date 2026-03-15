"""
Tests for Organisation models.

Tests cover the workflow of Catholic organisations managing events:
1. Creating organisations
2. Adding organisation contacts and controls
3. Inviting users to join organisations
4. Accepting invites
5. Verifying memberships (via invite, acceptance code, or manual verification)
6. Organisation involvement in events
7. Event sponsorship
8. Leadership/authority management
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from django.contrib.contenttypes.models import ContentType

from djmoney.money import Money

from apps.organisations.models import (
    Organisation, OrganisationContact, OrganisationControl,
    UserOrganisationMembership, OrganisationInvite, OrganisationAcceptanceCode,
    InvolvedEventOrganisation, InvolvedOrganisationRoleChoices,
    EventSponsor, EventSponsorPackage, Leader
)
from apps.events.models import Event, EventType

User = get_user_model()


class OrganisationModelTest(TestCase):
    """Test the Organisation model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='admin@stmarys.org',
            password='testpass123',
            first_name='John',
            last_name='Admin'
        )
    
    def test_create_organisation(self):
        """Test creating a basic organisation."""
        org = Organisation.objects.create(
            title='St. Mary\'s Catholic Church',
            description='A vibrant Catholic community',
            created_by=self.user
        )
        
        self.assertEqual(org.title, 'St. Mary\'s Catholic Church')
        self.assertEqual(org.created_by, self.user)
        self.assertFalse(org.required_acceptance_code)
        self.assertFalse(org.requires_manual_verification)
        self.assertIsNotNone(org.added_at)
    
    def test_organisation_unique_title(self):
        """Test that organisation titles must be unique."""
        Organisation.objects.create(
            title='St. Mary\'s Catholic Church',
            created_by=self.user
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            Organisation.objects.create(
                title='St. Mary\'s Catholic Church',
                created_by=self.user
            )
    
    def test_organisation_with_external_website(self):
        """Test organisation with external website."""
        org = Organisation.objects.create(
            title='Catholic Youth Ministry',
            external_website='https://www.cymnistry.org',
            created_by=self.user
        )
        
        self.assertEqual(org.external_website, 'https://www.cymnistry.org')
    
    def test_organisation_str_representation(self):
        """Test string representation of organisation."""
        org = Organisation.objects.create(
            title='St. Joseph Parish',
            created_by=self.user
        )
        
        self.assertEqual(str(org), 'St. Joseph Parish')


class OrganisationContactModelTest(TestCase):
    """Test the OrganisationContact model."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='admin@test.org',
            password='testpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.user
        )
    
    def test_create_organisation_contact(self):
        """Test creating an organisation contact."""
        contact = OrganisationContact.objects.create(
            organisation=self.organisation,
            name='Father Michael',
            email='fr.michael@parish.org',
            phone='+447123456789',
            label='Parish Priest'
        )
        
        self.assertEqual(contact.name, 'Father Michael')
        self.assertEqual(contact.email, 'fr.michael@parish.org')
        self.assertEqual(contact.label, 'Parish Priest')
        self.assertEqual(contact.organisation, self.organisation)
    
    def test_contact_str_representation(self):
        """Test string representation of contact."""
        contact = OrganisationContact.objects.create(
            organisation=self.organisation,
            name='Sister Anne',
            email='s.anne@parish.org'
        )
        
        self.assertEqual(str(contact), 'Sister Anne (Test Parish)')


class UserOrganisationMembershipTest(TestCase):
    """Test the UserOrganisationMembership model and workflow."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.member_user = User.objects.create_user(
            email='member@test.com',
            password='memberpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Holy Trinity Parish',
            created_by=self.admin
        )
    
    def test_create_membership(self):
        """Test creating a basic membership."""
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        self.assertEqual(membership.organisation, self.organisation)
        self.assertEqual(membership.user, self.member_user)
        self.assertEqual(membership.added_by, self.admin)
        self.assertIsNone(membership.verified_at)
    
    def test_membership_unique_together(self):
        """Test that a user can only have one membership per organisation."""
        UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            UserOrganisationMembership.objects.create(
                organisation=self.organisation,
                user=self.member_user,
                added_by=self.admin
            )
    
    def test_verify_with_invite_workflow(self):
        """Test verifying membership using an invite."""
        # Create membership
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        # Create invite
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.member_user,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        # Verify membership with invite
        self.assertIsNone(membership.verified_at)
        membership.verify_with_invite(invite)
        
        self.assertIsNotNone(membership.verified_at)
        self.assertTrue(invite.accepted)
        self.assertFalse(invite.is_active)
    
    def test_verify_with_invalid_invite_raises_error(self):
        """Test that using an invalid invite raises an error."""
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        # Create expired invite
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.member_user,
            invited_by=self.admin,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        with self.assertRaises(ValidationError) as context:
            membership.verify_with_invite(invite)
        
        self.assertIn('not valid', str(context.exception))
    
    def test_verify_with_code_workflow(self):
        """Test verifying membership using an acceptance code."""
        # Set organisation to require acceptance code
        self.organisation.required_acceptance_code = True
        self.organisation.save()
        
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        # Create acceptance code
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=10
        )
        
        # Verify membership with code
        self.assertIsNone(membership.verified_at)
        membership.verify_with_code(code)
        
        self.assertIsNotNone(membership.verified_at)
        self.assertEqual(code.uses, 1)
    
    def test_verify_with_code_requires_acceptance_code_setting(self):
        """Test that verification with code requires the setting."""
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        with self.assertRaises(ValidationError) as context:
            membership.verify_with_code('ANYCODE')
        
        self.assertIn('does not require an acceptance code', str(context.exception))
    
    def test_verify_manually_workflow(self):
        """Test manual verification of membership."""
        # Set organisation to require manual verification
        self.organisation.requires_manual_verification = True
        self.organisation.save()
        
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        # Manually verify
        self.assertIsNone(membership.verified_at)
        membership.verify_manually(verified_by=self.admin)
        
        self.assertIsNotNone(membership.verified_at)
    
    def test_requires_verification_property(self):
        """Test the requires_verification property."""
        membership = UserOrganisationMembership.objects.create(
            organisation=self.organisation,
            user=self.member_user,
            added_by=self.admin
        )
        
        self.assertFalse(membership.requires_verification)
        
        self.organisation.requires_manual_verification = True
        self.organisation.save()
        
        self.assertTrue(membership.requires_verification)


class OrganisationControlTest(TestCase):
    """Test the OrganisationControl model."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.controller = User.objects.create_user(
            email='controller@parish.org',
            password='controlpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Sacred Heart Parish',
            created_by=self.admin
        )
    
    def test_create_organisation_control(self):
        """Test creating organisation control."""
        control = OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller,
            added_by=self.admin
        )
        
        self.assertEqual(control.organisation, self.organisation)
        self.assertEqual(control.user, self.controller)
        self.assertEqual(control.added_by, self.admin)
    
    def test_control_unique_together(self):
        """Test that a user can only control an organisation once."""
        OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller,
            added_by=self.admin
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            OrganisationControl.objects.create(
                organisation=self.organisation,
                user=self.controller,
                added_by=self.admin
            )
    
    def test_control_str_representation(self):
        """Test string representation of control."""
        control = OrganisationControl.objects.create(
            organisation=self.organisation,
            user=self.controller,
            added_by=self.admin
        )
        
        expected = f"{self.controller.username} controls {self.organisation.title}"
        self.assertEqual(str(control), expected)


class OrganisationInviteTest(TestCase):
    """Test the OrganisationInvite model and invite workflow."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.invitee = User.objects.create_user(
            email='invitee@test.com',
            password='inviteepass123'
        )
        self.organisation = Organisation.objects.create(
            title='St. Francis Parish',
            created_by=self.admin
        )
    
    def test_create_invite(self):
        """Test creating an organisation invite."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.assertEqual(invite.organisation, self.organisation)
        self.assertEqual(invite.target_user, self.invitee)
        self.assertEqual(invite.invited_by, self.admin)
        self.assertFalse(invite.accepted)
        self.assertTrue(invite.is_active)
        self.assertTrue(invite.is_valid)
    
    def test_invite_unique_per_user_organisation(self):
        """Test that a user can only have one active invite per organisation."""
        OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            OrganisationInvite.objects.create(
                organisation=self.organisation,
                target_user=self.invitee,
                invited_by=self.admin
            )
    
    def test_invite_is_valid_when_active(self):
        """Test is_valid property for active invite."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.assertTrue(invite.is_valid)
    
    def test_invite_not_valid_when_expired(self):
        """Test is_valid property for expired invite."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        self.assertFalse(invite.is_valid)
    
    def test_invite_not_valid_when_already_accepted(self):
        """Test is_valid property for accepted invite."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin
        )
        
        invite.accept_invite()
        
        self.assertFalse(invite.is_valid)
        self.assertTrue(invite.accepted)
    
    def test_accept_invite_workflow(self):
        """Test accepting an invite."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=7)
        )
        
        self.assertFalse(invite.accepted)
        self.assertIsNone(invite.accepted_at)
        self.assertTrue(invite.is_active)
        
        invite.accept_invite()
        
        self.assertTrue(invite.accepted)
        self.assertIsNotNone(invite.accepted_at)
        self.assertFalse(invite.is_active)
    
    def test_cannot_accept_expired_invite(self):
        """Test that expired invites cannot be accepted."""
        invite = OrganisationInvite.objects.create(
            organisation=self.organisation,
            target_user=self.invitee,
            invited_by=self.admin,
            expires_at=timezone.now() - timedelta(days=1)
        )
        
        with self.assertRaises(ValidationError) as context:
            invite.accept_invite()
        
        self.assertIn('not valid', str(context.exception))
    
    def test_invite_expiry_in_past_raises_validation_error(self):
        """Test that creating invite with past expiry raises error."""
        with self.assertRaises(ValidationError):
            invite = OrganisationInvite(
                organisation=self.organisation,
                target_user=self.invitee,
                invited_by=self.admin,
                expires_at=timezone.now() - timedelta(days=1)
            )
            invite.clean()


class OrganisationAcceptanceCodeTest(TestCase):
    """Test the OrganisationAcceptanceCode model."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.organisation = Organisation.objects.create(
            title='St. Benedict Parish',
            created_by=self.admin,
            required_acceptance_code=True
        )
    
    def test_create_acceptance_code_with_auto_generation(self):
        """Test creating acceptance code with auto-generated code."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=10
        )
        
        self.assertIsNotNone(code.code)
        self.assertEqual(len(code.code), 10)
        self.assertTrue(code.code.isupper())
        self.assertTrue(code.code.isalnum())
        self.assertEqual(code.uses, 0)
        self.assertEqual(code.max_uses, 10)
        self.assertTrue(code.is_active)
    
    def test_create_acceptance_code_with_custom_code(self):
        """Test creating acceptance code with custom code."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            code='PARISH2024',
            added_by=self.admin,
            max_uses=5
        )
        
        self.assertEqual(code.code, 'PARISH2024')
        self.assertEqual(code.max_uses, 5)
    
    def test_acceptance_code_is_valid(self):
        """Test is_valid property for unused code."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=3
        )
        
        self.assertTrue(code.is_valid)
    
    def test_acceptance_code_not_valid_when_max_uses_reached(self):
        """Test is_valid property when max uses reached."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=1
        )
        
        code.use_code()
        
        self.assertFalse(code.is_valid)
        self.assertFalse(code.is_active)
    
    def test_acceptance_code_not_valid_when_expired(self):
        """Test is_valid property for expired code."""
        
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            expires_at=timezone.now() - timedelta(days=1)
        )
        self.assertFalse(code.is_valid)
            
    def test_use_code_increments_uses(self):
        """Test that using code increments the uses counter."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=5
        )
        
        self.assertEqual(code.uses, 0)
        code.use_code()
        self.assertEqual(code.uses, 1)
        
        code.use_code()
        self.assertEqual(code.uses, 2)
    
    def test_use_code_deactivates_when_max_reached(self):
        """Test that code is deactivated when max uses reached."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=2
        )
        
        code.use_code()
        self.assertTrue(code.is_active)
        
        code.use_code()
        self.assertFalse(code.is_active)
    
    def test_cannot_use_expired_code(self):
        """Test that expired codes cannot be used."""
        code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            expires_at=timezone.now() + timedelta(days=1)
        )
        
        # Manually set expiry to past
        code.expires_at = timezone.now() - timedelta(days=1)
        # code.save()
        
        with self.assertRaises(ValidationError) as context:
            code.use_code()
        
        self.assertIn('expired', str(context.exception))
    
    def test_is_single_use_property(self):
        """Test is_single_use property."""
        single_use_code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=1
        )
        
        multi_use_code = OrganisationAcceptanceCode.objects.create(
            organisation=self.organisation,
            added_by=self.admin,
            max_uses=10
        )
        
        self.assertTrue(single_use_code.is_single_use)
        self.assertFalse(multi_use_code.is_single_use)


class InvolvedEventOrganisationTest(TestCase):
    """Test the InvolvedEventOrganisation model."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Catholic Charities',
            created_by=self.admin
        )
        self.event_organisation = Organisation.objects.create(
            title='Event Host Organisation',
            created_by=self.admin
        )
        self.event_type = EventType.objects.create(
            title='Retreat',
            code='RET',
            created_by=self.admin
        )
        self.event = Event.objects.create(
            title='Youth Retreat 2024',
            display_code='YR2024',
            created_by=self.admin,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            organisation=self.event_organisation
        )
    
    def test_create_involved_organisation(self):
        """Test creating an involved organisation."""
        involvement = InvolvedEventOrganisation.objects.create(
            organisation=self.organisation,
            event=self.event,
            role=InvolvedOrganisationRoleChoices.ORGANISER,
            added_by=self.admin
        )
        
        self.assertEqual(involvement.organisation, self.organisation)
        self.assertEqual(involvement.event, self.event)
        self.assertEqual(involvement.role, InvolvedOrganisationRoleChoices.ORGANISER)
    
    def test_different_roles_for_same_org_event(self):
        """Test that an org can have different roles in the same event."""
        InvolvedEventOrganisation.objects.create(
            organisation=self.organisation,
            event=self.event,
            role=InvolvedOrganisationRoleChoices.ORGANISER,
            added_by=self.admin
        )
        
        # Same org can be a sponsor too
        InvolvedEventOrganisation.objects.create(
            organisation=self.organisation,
            event=self.event,
            role=InvolvedOrganisationRoleChoices.SPONSOR,
            added_by=self.admin
        )
        
        self.assertEqual(self.event.involved_organisations.count(), 2)
    
    def test_unique_together_constraint(self):
        """Test that org-event-role combination must be unique."""
        InvolvedEventOrganisation.objects.create(
            organisation=self.organisation,
            event=self.event,
            role=InvolvedOrganisationRoleChoices.PARTNER,
            added_by=self.admin
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            InvolvedEventOrganisation.objects.create(
                organisation=self.organisation,
                event=self.event,
                role=InvolvedOrganisationRoleChoices.PARTNER,
                added_by=self.admin
            )
    
    def test_organisation_role_choices(self):
        """Test different organisation role choices."""
        roles = [
            InvolvedOrganisationRoleChoices.COMMUNITY,
            InvolvedOrganisationRoleChoices.SPONSOR,
            InvolvedOrganisationRoleChoices.PARTNER,
            InvolvedOrganisationRoleChoices.ORGANISER,
            InvolvedOrganisationRoleChoices.VENUE_PROVIDER,
            InvolvedOrganisationRoleChoices.MEDIA_PARTNER,
        ]
        
        for role in roles:
            org = Organisation.objects.create(
                title=f'Org {role}',
                created_by=self.admin
            )
            involvement = InvolvedEventOrganisation.objects.create(
                organisation=org,
                event=self.event,
                role=role,
                added_by=self.admin
            )
            self.assertEqual(involvement.role, role)


class EventSponsorTest(TestCase):
    """Test the EventSponsor model."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Local Business Ltd',
            created_by=self.admin
        )
        self.event_organisation = Organisation.objects.create(
            title='Event Sponsor Test Organisation',
            created_by=self.admin
        )
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.admin
        )
        self.event = Event.objects.create(
            title='Catholic Conference 2024',
            display_code='CC2024',
            created_by=self.admin,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=62),
            organisation=self.event_organisation
        )
    
    def test_create_event_sponsor(self):
        """Test creating an event sponsor."""
        sponsor = EventSponsor.objects.create(
            name='Platinum Sponsor',
            description='Main sponsor for the conference',
            organisation=self.organisation,
            event=self.event,
            added_by=self.admin
        )
        
        self.assertEqual(sponsor.name, 'Platinum Sponsor')
        self.assertEqual(sponsor.organisation, self.organisation)
        self.assertEqual(sponsor.event, self.event)
        self.assertIsNotNone(sponsor.sponsor_id)
        self.assertEqual(sponsor.approval_status, 'PENDING')
        self.assertEqual(str(sponsor), 'Platinum Sponsor')


class EventSponsorPackageTest(TestCase):
    """Test the EventSponsorPackage model."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Sponsor Corp',
            created_by=self.admin
        )
        self.event_organisation = Organisation.objects.create(
            title='Event Package Test Organisation',
            created_by=self.admin
        )
        self.event_type = EventType.objects.create(
            title='Festival',
            code='FEST',
            created_by=self.admin
        )
        self.event = Event.objects.create(
            title='Catholic Arts Festival',
            display_code='CAF2024',
            created_by=self.admin,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=90),
            end_datetime=timezone.now() + timedelta(days=93),
            organisation=self.event_organisation
        )
        self.sponsor = EventSponsor.objects.create(
            name='Gold Sponsor',
            organisation=self.organisation,
            event=self.event,
            added_by=self.admin
        )
    
    def test_create_sponsor_package(self):
        """Test creating a sponsor package."""
        package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Gold Package',
            package_description='Premium sponsorship benefits',
            base_amount=5000.00
        )
        
        self.assertEqual(package.package_name, 'Gold Package')
        self.assertEqual(package.event, self.event)
        self.assertIsNotNone(package.package_id)
        self.assertEqual(package.base_amount.amount, Money(5000.00, 'GBP').amount)
    
    def test_sponsor_package_with_percentage_modifier(self):
        """Test sponsor package with percentage modifier."""
        package = EventSponsorPackage.objects.create(
            event=self.event,
            package_name='Early Bird Gold',
            base_amount=5000.00,
            percentage_modifier=-10.00  # 10% discount
        )
        
        self.assertEqual(package.percentage_modifier, -10.00)


class LeaderModelTest(TestCase):
    """Test the Leader model for generic authority relationships."""
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@parish.org',
            password='adminpass123'
        )
        self.leader_user = User.objects.create_user(
            email='leader@parish.org',
            password='leaderpass123'
        )
        self.organisation = Organisation.objects.create(
            title='Test Parish',
            created_by=self.admin
        )
    
    def test_create_leader_for_organisation(self):
        """Test creating a leader for an organisation."""
        content_type = ContentType.objects.get_for_model(Organisation)
        
        leader = Leader.objects.create(
            user=self.leader_user,
            target_type=content_type,
            target_id=self.organisation.id,
            notes='Parish coordinator',
            added_by=self.admin
        )
        
        self.assertEqual(leader.user, self.leader_user)
        self.assertEqual(leader.authority_object, self.organisation)
        self.assertEqual(leader.notes, 'Parish coordinator')
    
    def test_leader_unique_together(self):
        """Test that user-target_type-target_id combination must be unique."""
        content_type = ContentType.objects.get_for_model(Organisation)
        
        Leader.objects.create(
            user=self.leader_user,
            target_type=content_type,
            target_id=self.organisation.id,
            added_by=self.admin
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            Leader.objects.create(
                user=self.leader_user,
                target_type=content_type,
                target_id=self.organisation.id,
                added_by=self.admin
            )


class OrganisationWorkflowIntegrationTest(TestCase):
    """
    Integration test for the complete Catholic organisation workflow:
    1. Admin creates organisation
    2. Admin invites member
    3. Member accepts invite and gains membership
    4. Organisation gets involved in events
    5. Organisation sponsors events
    """
    
    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@holycross.org',
            password='adminpass123',
            first_name='Father',
            last_name='Patrick'
        )
        self.member1 = User.objects.create_user(
            email='mary@example.com',
            password='member1pass',
            first_name='Mary',
            last_name='Johnson'
        )
        self.member2 = User.objects.create_user(
            email='john@example.com',
            password='member2pass',
            first_name='John',
            last_name='Smith'
        )
    
    def test_complete_organisation_workflow(self):
        """Test the complete workflow from creation to event involvement."""
        
        # Step 1: Create organisation
        org = Organisation.objects.create(
            title='Holy Cross Parish',
            description='A welcoming Catholic community',
            external_website='https://holycross.org',
            created_by=self.admin
        )
        
        # Add contact information
        OrganisationContact.objects.create(
            organisation=org,
            name='Father Patrick',
            email='fr.patrick@holycross.org',
            phone='+447123456789',
            label='Parish Priest'
        )
        
        # Step 2: Set up organisation control
        OrganisationControl.objects.create(
            organisation=org,
            user=self.admin,
            added_by=self.admin
        )
        
        # Step 3: Invite members
        invite1 = OrganisationInvite.objects.create(
            organisation=org,
            target_user=self.member1,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=14)
        )
        
        invite2 = OrganisationInvite.objects.create(
            organisation=org,
            target_user=self.member2,
            invited_by=self.admin,
            expires_at=timezone.now() + timedelta(days=14)
        )
        
        # Step 4: Create memberships
        membership1 = UserOrganisationMembership.objects.create(
            organisation=org,
            user=self.member1,
            added_by=self.admin
        )
        
        membership2 = UserOrganisationMembership.objects.create(
            organisation=org,
            user=self.member2,
            added_by=self.admin
        )
        
        # Step 5: Member 1 accepts invite and gets verified
        # invite1.accept_invite()
        membership1.verify_with_invite(invite1)
        
        self.assertTrue(membership1.verified_at is not None)
        self.assertTrue(invite1.accepted)
        
        # Step 6: Member 2 uses acceptance code instead
        org.required_acceptance_code = True
        org.save()
        
        code = OrganisationAcceptanceCode.objects.create(
            organisation=org,
            code='HOLYCROSS24',
            added_by=self.admin,
            max_uses=50
        )
        
        membership2.verify_with_code(code)
        
        self.assertTrue(membership2.verified_at is not None)
        self.assertEqual(code.uses, 1)
        
        # Step 7: Create an event
        event_type = EventType.objects.create(
            title='Pilgrimage',
            code='PIL',
            created_by=self.admin
        )
        
        event = Event.objects.create(
            title='Lourdes Pilgrimage 2024',
            display_code='LP2024',
            created_by=self.admin,
            event_type=event_type,
            start_datetime=timezone.now() + timedelta(days=180),
            end_datetime=timezone.now() + timedelta(days=187),
            organisation=org
        )
        
        # Step 8: Organisation gets involved as organiser
        InvolvedEventOrganisation.objects.create(
            organisation=org,
            event=event,
            role=InvolvedOrganisationRoleChoices.ORGANISER,
            added_by=self.admin
        )
        
        # Step 9: Add sponsor
        sponsor_org = Organisation.objects.create(
            title='Catholic Travel Agency',
            created_by=self.admin
        )
        
        sponsor = EventSponsor.objects.create(
            name='Travel Sponsor',
            organisation=sponsor_org,
            event=event,
            added_by=self.admin
        )
        
        package = EventSponsorPackage.objects.create(
            event=event,
            package_name='Bronze Package',
            base_amount=1000.00
        )
        sponsor.package = package
        sponsor.save(update_fields=['package'])
        
        # Verify everything is connected
        self.assertEqual(org.memberships.count(), 2)
        self.assertEqual(org.memberships.filter(verified_at__isnull=False).count(), 2)
        self.assertEqual(event.involved_organisations.count(), 1)
        self.assertEqual(event.sponsors.count(), 1)
        self.assertEqual(org.contacts.count(), 1)
        self.assertEqual(org.controllers.count(), 1)
