"""
Attendee Statistics Tests

Comprehensive test suite for attendee statistics functionality testing:
- Core statistics calculation functions
- API endpoints with raw and ECharts formats
- Event filtering capabilities
- Soft-delete handling
- Edge cases and data accuracy
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import date, timedelta
from decimal import Decimal

from apps.attendee.models import (
    Attendee, AttendeeRelationship,
    AccessibilityRequirement, AttendeeAccessibilityRequirement,
    DietaryRequirement, AttendeeDietaryRequirement,
    MedicalCondition, AttendeeMedicalCondition,
    EmergencyContact, Consent, AttendeeConsent,
    EventAttendance
)
from apps.attendee import statistics
from apps.events.models import Event, EventType, EventStatusChoices
from apps.organisations.models import Organisation
from apps.locations.models import (
    AreaLocation, CountryLocation, ClusterLocation, ChapterLocation,
    GeneralSectorType, SpecificSectorType
)

User = get_user_model()


class AttendeeStatisticsBaseTestCase(TestCase):
    """Base test case with common setup for attendee statistics tests."""
    
    def setUp(self):
        """Set up comprehensive test data for statistics testing."""
        self.client = APIClient()
        
        # Create users
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        
        self.admin_user = User.objects.create_user(
            username='adminuser',
            email='admin@example.com',
            password='testpass123',
            is_staff=True
        )
        
        # Create organization
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organization for statistics',
            created_by=self.user
        )
        
        # Create event type
        self.event_type = EventType.objects.create(
            title='Conference',
            code='CONF',
            created_by=self.user
        )
        
        # Create events
        self.event1 = Event.objects.create(
            title='Conference 2026',
            display_code='CONF2026',
            display_identifier='CONF2026TEST123',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation
        )
        
        self.event2 = Event.objects.create(
            title='Workshop 2026',
            display_code='WORK2026',
            display_identifier='WORK2026TEST456',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=62),
            status=EventStatusChoices.PUBLISHED,
            organisation=self.organisation
        )
        
        # Create location hierarchy
        self.country = CountryLocation.objects.create(
            country="UK",
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE
        )
        
        self.cluster = ClusterLocation.objects.create(
            cluster_name='South Cluster',
            country=self.country
        )
        
        self.chapter = ChapterLocation.objects.create(
            chapter_name='London Chapter',
            cluster=self.cluster
        )
        
        self.area1 = AreaLocation.objects.create(
            area_name='Westminster',
            area_code='WM',
            chapter=self.chapter
        )
        
        self.area2 = AreaLocation.objects.create(
            area_name='Camden',
            area_code='CMD',
            chapter=self.chapter
        )
        
        # Create medical conditions
        self.diabetes = MedicalCondition.objects.create(
            label='Diabetes',
            code='DIABETES'
        )
        
        self.asthma = MedicalCondition.objects.create(
            label='Asthma',
            code='ASTHMA'
        )
        
        # Create accessibility requirements
        self.wheelchair = AccessibilityRequirement.objects.create(
            label='Wheelchair Access',
            code='WHEELCHAIR'
        )
        
        self.hearing_loop = AccessibilityRequirement.objects.create(
            label='Hearing Loop',
            code='HEAR_LOOP'
        )
        
        # Create dietary requirements
        self.vegetarian = DietaryRequirement.objects.create(
            label='Vegetarian',
            code='VEGETARIAN'
        )
        
        self.gluten_free = DietaryRequirement.objects.create(
            label='Gluten Free',
            code='GLUTEN_FREE'
        )
        
        # Create consents for event1
        self.consent_photo = Consent.objects.create(
            event=self.event1,
            code='PHOTO',
            title='Photo Consent',
            required=True,
            active=True
        )
        
        self.consent_newsletter = Consent.objects.create(
            event=self.event1,
            code='NEWSLETTER',
            title='Newsletter Consent',
            required=False,
            active=True
        )
        
        # Create diverse attendees for event1
        self._create_attendee_with_details(
            first_name='John',
            last_name='Doe',
            event=self.event1,
            date_of_birth=date(1990, 5, 15),  # Age ~35
            gender='MALE',
            relationship=AttendeeRelationship.SELF,
            area=self.area1,
            medical_conditions=[self.diabetes],
            medical_severity='moderate',
            accessibility=[self.wheelchair],
            dietary=[self.vegetarian],
            has_emergency_contact=True,
            emergency_relationship='spouse',
            consents={self.consent_photo: True, self.consent_newsletter: True}
        )
        
        self._create_attendee_with_details(
            first_name='Jane',
            last_name='Smith',
            event=self.event1,
            date_of_birth=date(1985, 8, 22),  # Age ~40
            gender='FEMALE',
            relationship=AttendeeRelationship.SPOUSE,
            area=self.area1,
            medical_conditions=[self.asthma],
            medical_severity='mild',
            accessibility=[],
            dietary=[self.gluten_free],
            has_emergency_contact=True,
            emergency_relationship='parent',
            consents={self.consent_photo: True, self.consent_newsletter: False}
        )
        
        self._create_attendee_with_details(
            first_name='Bob',
            last_name='Johnson',
            event=self.event1,
            date_of_birth=date(2005, 3, 10),  # Age ~20
            gender='MALE',
            relationship=AttendeeRelationship.CHILD,
            area=self.area2,
            medical_conditions=[],
            accessibility=[self.hearing_loop],
            dietary=[],
            has_emergency_contact=True,
            emergency_relationship='parent',
            consents={self.consent_photo: False, self.consent_newsletter: False}
        )
        
        self._create_attendee_with_details(
            first_name='Alice',
            last_name='Williams',
            event=self.event1,
            date_of_birth=date(2010, 11, 5),  # Age ~15
            gender='FEMALE',
            relationship=AttendeeRelationship.CHILD,
            area=self.area2,
            medical_conditions=[self.diabetes, self.asthma],
            medical_severity='severe',
            accessibility=[self.wheelchair],
            dietary=[self.vegetarian, self.gluten_free],
            has_emergency_contact=True,
            emergency_relationship='parent',
            consents={self.consent_photo: True, self.consent_newsletter: True}
        )
        
        self._create_attendee_with_details(
            first_name='Charlie',
            last_name='Brown',
            event=self.event1,
            date_of_birth=date(1992, 6, 18),  # Age ~33 - DOB required by model
            gender='MALE',
            relationship=AttendeeRelationship.FRIEND,
            area=None,  # No area
            medical_conditions=[],
            accessibility=[],
            dietary=[],
            has_emergency_contact=False,
            consents={self.consent_photo: True, self.consent_newsletter: False}
        )
        
        # Create attendees for event2
        self._create_attendee_with_details(
            first_name='David',
            last_name='Miller',
            event=self.event2,
            date_of_birth=date(1995, 7, 20),  # Age ~30
            gender='MALE',
            relationship=AttendeeRelationship.SELF,
            area=self.area1,
            medical_conditions=[],
            accessibility=[],
            dietary=[self.vegetarian],
            has_emergency_contact=True,
            emergency_relationship='sibling'
        )
        
        self._create_attendee_with_details(
            first_name='Emma',
            last_name='Davis',
            event=self.event2,
            date_of_birth=date(2000, 1, 15),  # Age ~26
            gender='FEMALE',
            relationship=AttendeeRelationship.SELF,
            area=self.area1,
            medical_conditions=[self.asthma],
            medical_severity='mild',
            accessibility=[],
            dietary=[],
            has_emergency_contact=True,
            emergency_relationship='friend'
        )
        
        # Create a soft-deleted attendee for event1
        deleted_attendee = self._create_attendee_with_details(
            first_name='Deleted',
            last_name='User',
            event=self.event1,
            date_of_birth=date(1988, 4, 12),
            gender='OTHER',
            relationship=AttendeeRelationship.OTHER,
            area=self.area1,
            medical_conditions=[],
            accessibility=[],
            dietary=[],
            has_emergency_contact=False
        )
        deleted_attendee.soft_delete()
        # Soft delete using queryset update to bypass validation
        # Attendee.objects.filter(pk=deleted_attendee.pk).update(deleted_at=timezone.now())
        
        # Create attendance records for event1
        self.attendance1 = EventAttendance.objects.create(
            attendee=Attendee.objects.filter(
                first_name='John',
                event=self.event1
            ).first(),
            event=self.event1,
            check_in_time=timezone.now() - timedelta(days=1),
            check_in_by=self.user
        )
        
        self.attendance2 = EventAttendance.objects.create(
            attendee=Attendee.objects.filter(
                first_name='Jane',
                event=self.event1
            ).first(),
            event=self.event1,
            check_in_time=timezone.now() - timedelta(days=1),
            check_in_by=self.user
        )
        
        # Not checked in
        self.attendance3 = EventAttendance.objects.create(
            attendee=Attendee.objects.filter(
                first_name='Bob',
                event=self.event1
            ).first(),
            event=self.event1
        )
    
    def _create_attendee_with_details(
        self,
        first_name,
        last_name,
        event,
        date_of_birth=None,
        gender='MALE',
        relationship=AttendeeRelationship.SELF,
        area=None,
        medical_conditions=None,
        medical_severity=None,
        accessibility=None,
        dietary=None,
        has_emergency_contact=False,
        emergency_relationship=None,
        consents=None
    ):
        """Helper to create an attendee with related data."""
        attendee = Attendee.objects.create(
            first_name=first_name,
            last_name=last_name,
            email=f'{first_name.lower()}.{last_name.lower()}@example.com',
            event=event,
            user=self.user,
            date_of_birth=date_of_birth,
            gender=gender,
            relationship_to_user=relationship,
            defined_by=self.user,
            area_from=area
        )
        
        # Add medical conditions
        if medical_conditions:
            for condition in medical_conditions:
                AttendeeMedicalCondition.objects.create(
                    attendee=attendee,
                    medical_condition=condition,
                    severity=medical_severity
                )
        
        # Add accessibility requirements
        if accessibility:
            for req in accessibility:
                AttendeeAccessibilityRequirement.objects.create(
                    attendee=attendee,
                    accessibility_requirement=req
                )
        
        # Add dietary requirements
        if dietary:
            for req in dietary:
                AttendeeDietaryRequirement.objects.create(
                    attendee=attendee,
                    dietary_requirement=req
                )
        
        # Add emergency contact
        if has_emergency_contact:
            EmergencyContact.objects.create(
                attendee=attendee,
                first_name=f'{first_name}Emergency',
                last_name='Contact',
                phone_number='+1234567890',
                relationship=emergency_relationship or 'parent'
            )
        
        # Add consents
        if consents:
            for consent, given in consents.items():
                AttendeeConsent.objects.create(
                    attendee=attendee,
                    consent=consent,
                    consent_given=given
                )
        
        return attendee


class AgeDistributionStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for age distribution statistics calculation."""
    
    def test_age_distribution_ranges(self):
        """Test age distribution with range grouping."""
        result = statistics.calculate_age_distribution(
            event_id=str(self.event1.event_id),
            grouping='ranges'
        )
        
        self.assertEqual(result['total_with_age'], 5)  # All 5 attendees have DOB now
        self.assertEqual(result['total_without_age'], 0)  # None without DOB
        self.assertIsNotNone(result['average_age'])
        self.assertGreater(result['average_age'], 0)
        
        # Check distribution structure
        self.assertIsInstance(result['distribution'], list)
        age_ranges = [item['label'] for item in result['distribution']]
        self.assertIn('13-17', age_ranges)
        self.assertIn('18-25', age_ranges)
        self.assertIn('26-35', age_ranges)
        
        # Verify percentages sum to 100 (within rounding)
        total_percentage = sum(item['percentage'] for item in result['distribution'])
        self.assertAlmostEqual(total_percentage, 100.0, places=0)
    
    def test_age_distribution_individual(self):
        """Test age distribution with individual age grouping."""
        result = statistics.calculate_age_distribution(
            event_id=str(self.event1.event_id),
            grouping='individual'
        )
        
        self.assertEqual(result['total_with_age'], 5)  # All have DOB
        # Distribution should show individual ages
        self.assertGreater(len(result['distribution']), 0)
        # Each item should have integer age as label
        for item in result['distribution']:
            self.assertTrue(item['label'].isdigit())
    
    def test_age_distribution_global(self):
        """Test age distribution across all events."""
        result = statistics.calculate_age_distribution()
        
        # Should include attendees from both events (7 total with age, all active)
        self.assertEqual(result['total_with_age'], 7)
        self.assertEqual(result['total_without_age'], 0)
    
    def test_age_distribution_include_deleted(self):
        """Test age distribution including soft-deleted attendees."""
        result = statistics.calculate_age_distribution(
            event_id=str(self.event1.event_id),
            include_deleted=True
        )
        
        # Should include 6 with age (5 active + 1 deleted)
        self.assertEqual(result['total_with_age'], 6)
    
    def test_age_distribution_empty_event(self):
        """Test age distribution with no attendees."""
        empty_event = Event.objects.create(
            title='Empty Event',
            display_code='EMPTY',
            display_identifier='EMPTY2026TEST',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=90),
            end_datetime=timezone.now() + timedelta(days=92),
            status=EventStatusChoices.PUBLISHED,
            organisation=self.organisation
        )
        
        result = statistics.calculate_age_distribution(
            event_id=str(empty_event.event_id)
        )
        
        self.assertEqual(result['total_with_age'], 0)
        self.assertEqual(result['total_without_age'], 0)
        self.assertIsNone(result['average_age'])


class GenderDistributionStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for gender distribution statistics."""
    
    def test_gender_distribution_basic(self):
        """Test basic gender distribution calculation."""
        result = statistics.calculate_gender_distribution(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total'], 5)  # 5 active attendees
        self.assertIsInstance(result['distribution'], list)
        
        # Check for male and female
        genders = [item['label'] for item in result['distribution']]
        self.assertIn('MALE', genders)
        self.assertIn('FEMALE', genders)
        
        # Verify counts
        male_count = next(
            (item['value'] for item in result['distribution'] if item['label'] == 'MALE'),
            0
        )
        female_count = next(
            (item['value'] for item in result['distribution'] if item['label'] == 'FEMALE'),
            0
        )
        self.assertEqual(male_count, 3)
        self.assertEqual(female_count, 2)
    
    def test_gender_distribution_percentages(self):
        """Test gender distribution percentage calculations."""
        result = statistics.calculate_gender_distribution(
            event_id=str(self.event1.event_id)
        )
        
        # Verify percentages sum to 100
        total_percentage = sum(item['percentage'] for item in result['distribution'])
        self.assertAlmostEqual(total_percentage, 100.0, places=1)
    
    def test_gender_distribution_global(self):
        """Test gender distribution across all events."""
        result = statistics.calculate_gender_distribution()
        
        # Should include all active attendees from both events
        self.assertEqual(result['total'], 7)


class RelationshipDistributionStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for relationship distribution statistics."""
    
    def test_relationship_distribution_basic(self):
        """Test basic relationship distribution."""
        result = statistics.calculate_relationship_distribution(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total'], 5)
        self.assertIsInstance(result['distribution'], list)
        
        # Should have relationship codes
        for item in result['distribution']:
            self.assertIn('code', item)
            self.assertIn('label', item)
    
    def test_relationship_distribution_counts(self):
        """Test relationship distribution counts."""
        result = statistics.calculate_relationship_distribution(
            event_id=str(self.event1.event_id)
        )
        
        # Check specific relationships
        relationships = {item['code']: item['value'] for item in result['distribution']}
        self.assertEqual(relationships.get(AttendeeRelationship.SELF), 1)
        self.assertEqual(relationships.get(AttendeeRelationship.CHILD), 2)


class AreaDistributionStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for area distribution statistics."""
    
    def test_area_distribution_basic(self):
        """Test basic area distribution."""
        result = statistics.calculate_area_distribution(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total'], 5)
        self.assertEqual(result['total_without_area'], 1)  # Charlie has no area still
        self.assertEqual(result['total_with_area'], 4)
        
        # Check areas are listed
        areas = [item['label'] for item in result['distribution']]
        self.assertIn('Westminster', areas)
        self.assertIn('Camden', areas)
    
    def test_area_distribution_counts(self):
        """Test area distribution counts."""
        result = statistics.calculate_area_distribution(
            event_id=str(self.event1.event_id)
        )
        
        area_counts = {item['label']: item['value'] for item in result['distribution']}
        self.assertEqual(area_counts.get('Westminster'), 2)
        self.assertEqual(area_counts.get('Camden'), 2)


class MedicalConditionsStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for medical conditions statistics."""
    
    def test_medical_conditions_basic(self):
        """Test basic medical conditions statistics."""
        result = statistics.calculate_medical_conditions_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_attendees'], 5)
        self.assertEqual(result['attendees_with_conditions'], 3)
        self.assertEqual(result['attendees_without_conditions'], 2)
    
    def test_medical_conditions_breakdown(self):
        """Test medical conditions breakdown."""
        result = statistics.calculate_medical_conditions_stats(
            event_id=str(self.event1.event_id)
        )
        
        conditions = {item['code']: item for item in result['conditions']}
        self.assertIn('DIABETES', conditions)
        self.assertIn('ASTHMA', conditions)
        
        # Verify counts
        self.assertEqual(conditions['DIABETES']['value'], 2)  # John and Alice
        self.assertEqual(conditions['ASTHMA']['value'], 2)  # Jane and Alice
    
    def test_medical_conditions_severity(self):
        """Test medical conditions severity distribution."""
        result = statistics.calculate_medical_conditions_stats(
            event_id=str(self.event1.event_id)
        )
        
        # Check severity distribution exists
        self.assertIn('severity_distribution', result)
        severity = {
            item['label'].lower(): item['value']
            for item in result['severity_distribution']
        }
        
        self.assertIn('mild', severity)
        self.assertIn('moderate', severity)


class AccessibilityRequirementsStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for accessibility requirements statistics."""
    
    def test_accessibility_requirements_basic(self):
        """Test basic accessibility requirements statistics."""
        result = statistics.calculate_accessibility_requirements_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_attendees'], 5)
        self.assertEqual(result['attendees_with_requirements'], 3)
    
    def test_accessibility_requirements_breakdown(self):
        """Test accessibility requirements breakdown."""
        result = statistics.calculate_accessibility_requirements_stats(
            event_id=str(self.event1.event_id)
        )
        
        requirements = {item['code']: item for item in result['requirements']}
        self.assertIn('WHEELCHAIR', requirements)
        self.assertIn('HEAR_LOOP', requirements)


class DietaryRequirementsStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for dietary requirements statistics."""
    
    def test_dietary_requirements_basic(self):
        """Test basic dietary requirements statistics."""
        result = statistics.calculate_dietary_requirements_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_attendees'], 5)
        self.assertEqual(result['attendees_with_requirements'], 3)
    
    def test_dietary_requirements_breakdown(self):
        """Test dietary requirements breakdown."""
        result = statistics.calculate_dietary_requirements_stats(
            event_id=str(self.event1.event_id)
        )
        
        requirements = {item['code']: item for item in result['requirements']}
        self.assertIn('VEGETARIAN', requirements)
        self.assertIn('GLUTEN_FREE', requirements)


class EmergencyContactStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for emergency contact statistics."""
    
    def test_emergency_contacts_basic(self):
        """Test basic emergency contact statistics."""
        result = statistics.calculate_emergency_contact_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_attendees'], 5)
        self.assertEqual(result['attendees_with_contacts'], 4)
        self.assertEqual(result['attendees_without_contacts'], 1)
    
    def test_emergency_contacts_relationships(self):
        """Test emergency contact relationship breakdown."""
        result = statistics.calculate_emergency_contact_stats(
            event_id=str(self.event1.event_id)
        )
        
        relationships = [item['label'].lower() for item in result['relationships']]
        self.assertIn('parent', relationships)
        self.assertIn('spouse', relationships)


class ConsentStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for consent statistics."""
    
    def test_consent_stats_basic(self):
        """Test basic consent statistics."""
        result = statistics.calculate_consent_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_attendees'], 5)
        self.assertEqual(result['total_consents'], 2)
    
    def test_consent_stats_breakdown(self):
        """Test consent breakdown with completion and approval rates."""
        result = statistics.calculate_consent_stats(
            event_id=str(self.event1.event_id)
        )
        
        consents = {item['consent_code']: item for item in result['consent_breakdown']}
        
        # Photo consent
        photo = consents['PHOTO']
        self.assertEqual(photo['total_responses'], 5)
        self.assertEqual(photo['consents_given'], 4)  # 4 gave consent
        self.assertEqual(photo['consents_declined'], 1)  # 1 declined
        self.assertEqual(photo['completion_rate'], 100.0)
        self.assertEqual(photo['approval_rate'], 80.0)
        
        # Newsletter consent
        newsletter = consents['NEWSLETTER']
        self.assertEqual(newsletter['total_responses'], 5)
        self.assertEqual(newsletter['consents_given'], 2)
        self.assertEqual(newsletter['approval_rate'], 40.0)
    
    def test_consent_stats_requires_event_id(self):
        """Test that consent stats require event_id."""
        result = statistics.calculate_consent_stats()
        
        self.assertIn('message', result)
        self.assertIn('event_id', result['message'])


class RegistrationTrendsStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for registration trends statistics."""
    
    def test_registration_trends_day(self):
        """Test registration trends grouped by day."""
        result = statistics.calculate_registration_trends(
            event_id=str(self.event1.event_id),
            group_by='day'
        )
        
        self.assertEqual(result['group_by'], 'day')
        self.assertIsInstance(result['trends'], list)
        self.assertGreater(len(result['trends']), 0)
        
        # Each trend item should have date and count
        for item in result['trends']:
            self.assertIn('date', item)
            self.assertIn('count', item)
    
    def test_registration_trends_week(self):
        """Test registration trends grouped by week."""
        result = statistics.calculate_registration_trends(
            event_id=str(self.event1.event_id),
            group_by='week'
        )
        
        self.assertEqual(result['group_by'], 'week')
    
    def test_registration_trends_month(self):
        """Test registration trends grouped by month."""
        result = statistics.calculate_registration_trends(
            event_id=str(self.event1.event_id),
            group_by='month'
        )
        
        self.assertEqual(result['group_by'], 'month')
    
    def test_registration_trends_date_filtering(self):
        """Test registration trends with date filtering."""
        today = date.today()
        date_from = today - timedelta(days=7)
        date_to = today
        
        result = statistics.calculate_registration_trends(
            event_id=str(self.event1.event_id),
            date_from=date_from,
            date_to=date_to
        )
        
        self.assertEqual(result['date_from'], date_from.isoformat())
        self.assertEqual(result['date_to'], date_to.isoformat())


class AttendanceStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for attendance statistics."""
    
    def test_attendance_stats_basic(self):
        """Test basic attendance statistics."""
        result = statistics.calculate_attendance_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertEqual(result['total_attendees'], 5)
        self.assertEqual(result['checked_in'], 2)
        self.assertEqual(result['not_checked_in'], 3)
        self.assertEqual(result['check_in_rate'], 40.0)
    
    def test_attendance_stats_trends(self):
        """Test attendance check-in trends."""
        result = statistics.calculate_attendance_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertIn('check_in_trends', result)
        self.assertIsInstance(result['check_in_trends'], list)


class OverviewStatisticsTests(AttendeeStatisticsBaseTestCase):
    """Tests for overview statistics (combined)."""
    
    def test_overview_stats_structure(self):
        """Test overview statistics structure."""
        result = statistics.calculate_overview_stats(
            event_id=str(self.event1.event_id)
        )
        
        self.assertIn('total_attendees', result)
        self.assertIn('demographics', result)
        self.assertIn('personal_info', result)
        self.assertIn('generated_at', result)
    
    def test_overview_stats_demographics(self):
        """Test overview statistics demographics section."""
        result = statistics.calculate_overview_stats(
            event_id=str(self.event1.event_id)
        )
        
        demographics = result['demographics']
        self.assertIn('gender', demographics)
        self.assertIn('age', demographics)
        self.assertIn('relationships', demographics)
    
    def test_overview_stats_personal_info(self):
        """Test overview statistics personal info section."""
        result = statistics.calculate_overview_stats(
            event_id=str(self.event1.event_id)
        )
        
        personal_info = result['personal_info']
        self.assertIn('medical_conditions', personal_info)
        self.assertIn('accessibility_requirements', personal_info)
        self.assertIn('dietary_requirements', personal_info)
        self.assertIn('emergency_contacts', personal_info)
        
        # Verify counts
        self.assertEqual(personal_info['medical_conditions'], 3)
        self.assertEqual(personal_info['accessibility_requirements'], 3)
        self.assertEqual(personal_info['dietary_requirements'], 3)
        self.assertEqual(personal_info['emergency_contacts'], 4)


class AttendeeStatisticsAPITests(AttendeeStatisticsBaseTestCase):
    """Tests for attendee statistics API endpoints."""
    
    def test_list_endpoints(self):
        """Test listing available endpoints."""
        self.client.force_authenticate(user=self.user)
        # The statistics viewset uses action decorators, not a list endpoint
        # Test the overview endpoint instead which acts as a summary
        response = self.client.get(f'/api/attendees/statistics/overview/?event_id={self.event1.event_id}')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('demographics', response.data)
    
    def test_age_distribution_api_raw(self):
        """Test age distribution API with raw format."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/age-distribution/?event_id={self.event1.event_id}&format=raw'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total_with_age', response.data)
        self.assertIn('distribution', response.data)
        self.assertNotIn('chart', response.data)  # Raw shouldn't have chart
    
    def test_age_distribution_api_echarts(self):
        """Test age distribution API with ECharts format."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/age-distribution/?event_id={self.event1.event_id}&format=echarts'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('chart', response.data)  # ECharts should have chart config
        
        # Verify chart structure
        chart = response.data['chart']
        self.assertIn('title', chart)
        self.assertIn('series', chart)
    
    def test_gender_distribution_api(self):
        """Test gender distribution API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/gender-distribution/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('distribution', response.data)
    
    def test_demographics_api(self):
        """Test combined demographics API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/demographics/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('age', response.data)
        self.assertIn('gender', response.data)
        self.assertIn('relationships', response.data)
        self.assertIn('areas', response.data)
    
    def test_personal_info_api(self):
        """Test personal info combined API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/personal-info/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The API returns 'medical', 'accessibility', 'dietary', 'emergency_contacts'
        self.assertIn('medical', response.data)
        self.assertIn('accessibility', response.data)
        self.assertIn('dietary', response.data)
        self.assertIn('emergency_contacts', response.data)
    
    def test_consents_api(self):
        """Test consents API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/consents/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('consent_breakdown', response.data)
    
    def test_registration_trends_api(self):
        """Test registration trends API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/registration-trends/?event_id={self.event1.event_id}&group_by=day'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('trends', response.data)
    
    def test_attendance_api(self):
        """Test attendance statistics API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/attendance/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('checked_in', response.data)
        self.assertIn('check_in_rate', response.data)
    
    def test_overview_api(self):
        """Test overview statistics API."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f'/api/attendees/statistics/overview/?event_id={self.event1.event_id}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('total_attendees', response.data)
        self.assertIn('demographics', response.data)
        self.assertIn('personal_info', response.data)
    
    def test_authentication_required(self):
        """Test that authentication is required for statistics endpoints."""
        response = self.client.get('/api/attendees/statistics/demographics/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_global_statistics(self):
        """Test getting global statistics without event_id."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/attendees/statistics/age-distribution/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should include attendees from all events
        self.assertGreaterEqual(response.data['total_with_age'], 6)
    
    def test_include_deleted_parameter(self):
        """Test include_deleted parameter."""
        self.client.force_authenticate(user=self.user)
        
        # Without deleted
        response1 = self.client.get(
            f'/api/attendees/statistics/gender-distribution/?event_id={self.event1.event_id}'
        )
        total_without_deleted = response1.data['total']
        
        # With deleted
        response2 = self.client.get(
            f'/api/attendees/statistics/gender-distribution/?event_id={self.event1.event_id}&include_deleted=true'
        )
        total_with_deleted = response2.data['total']

        print(Attendee.objects.all())
        
        # Should be different - deleted attendee should be included
        self.assertEqual(total_without_deleted, 5)
        self.assertEqual(total_with_deleted, 6)
        self.assertEqual(total_with_deleted, total_without_deleted + 1)
    
    def test_invalid_event_id(self):
        """Test API with invalid event_id."""
        self.client.force_authenticate(user=self.user)
        # Use a valid UUID format that doesn't exist
        response = self.client.get(
            '/api/attendees/statistics/demographics/?event_id=00000000-0000-0000-0000-000000000000'
        )
        
        # Should still return 200 but with empty data
        self.assertEqual(response.status_code, status.HTTP_200_OK)
