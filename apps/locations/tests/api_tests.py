"""
API Tests for Locations endpoints.

Tests cover the complete API workflow for location management:
1. Country locations CRUD with permissions
2. Cluster locations with country relations
3. Chapter locations with cluster relations
4. Area locations with chapter relations and relative area search
5. Relative area management
6. POI CRUD operations
7. Venue management with POI relations
8. Room venue management
9. Venue contacts and metadata
10. HATEOAS link validation
11. Filtering and search
12. Leader integration with locations
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta

from apps.locations.models import (
    CountryLocation, ClusterLocation, ChapterLocation, AreaLocation, RelativeArea,
    POI, Venue, RoomVenue, VenueContact, VenueMetadata,
    GeneralSectorType, SpecificSectorType, POITypeChoice, VenueContactRoleChoice
)
from apps.organisations.models import Leader, Organisation

User = get_user_model()


class BaseLocationAPITestCase(TestCase):
    """Base test case with common setup for location tests."""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create users
        self.admin_user = User.objects.create_user(
            email='admin@amdg.org',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )
        self.staff_user = User.objects.create_user(
            email='staff@amdg.org',
            password='staffpass123',
            is_staff=True
        )
        self.regular_user = User.objects.create_user(
            email='user@example.com',
            password='userpass123'
        )
        
        # Create organisation for leader tests
        self.organisation = Organisation.objects.create(
            title='Test Organisation',
            description='Test organisation',
            created_by=self.admin_user
        )
        
        # Create location hierarchy
        self.country = CountryLocation.objects.create(
            country='GB',
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE,
            active=True
        )
        
        self.cluster = ClusterLocation.objects.create(
            cluster_name='London Cluster',
            cluster_code='LON',
            country=self.country,
            description='London area cluster',
            active=True
        )
        
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Central London',
            chapter_code='CL',
            cluster=self.cluster,
            description='Central London chapter',
            active=True
        )
        
        self.area = AreaLocation.objects.create(
            area_name='Westminster',
            area_code='WM',
            chapter=self.chapter,
            description='Westminster area',
            active=True
        )
        
        # Create relative area for search testing
        self.relative_area = RelativeArea.objects.create(
            name='Victoria',
            relative_area=self.area
        )
        
        # Create POI and Venue
        self.poi = POI.objects.create(
            name='Convention Centre',
            description='Large convention centre',
            address='123 Main Street',
            city='London',
            postcode='SW1A 1AA',
            poi_type=POITypeChoice.VENUE,
            latitude=51.5074,
            longitude=-0.1278,
            created_by=self.regular_user
        )
        
        self.venue = Venue.objects.create(
            poi=self.poi,
            description='Main convention venue',
            capacity=500,
            added_by=self.regular_user
        )


class CountryLocationAPITest(BaseLocationAPITestCase):
    """Test CountryLocation API endpoints."""
    
    def test_list_countries_unauthenticated(self):
        """Test listing countries without authentication."""
        url = reverse('locations:country-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_list_countries_authenticated(self):
        """Test listing countries with authentication."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:country-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data['results'][0])
    
    def test_retrieve_country_detail(self):
        """Test retrieving country details."""
        url = reverse('locations:country-detail', kwargs={'pk': self.country.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['country'], 'GB')
        self.assertIn('_links', response.data)
        self.assertIn('clusters', response.data)
    
    def test_create_country_requires_staff(self):
        """Test creating country requires staff permissions."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:country-list')
        data = {
            'country': 'FR',
            'general_sector': GeneralSectorType.EUROPE,
            'specific_sector': SpecificSectorType.WEST_EUROPE,
            'active': True
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_create_country_as_staff(self):
        """Test creating country as staff user."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('locations:country-list')
        data = {
            'country': 'FR',
            'general_sector': GeneralSectorType.EUROPE,
            'specific_sector': SpecificSectorType.WEST_EUROPE,
            'active': True
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['country'], 'FR')
    
    def test_filter_countries_by_sector(self):
        """Test filtering countries by sector."""
        url = reverse('locations:country-list')
        response = self.client.get(url, {'general_sector': GeneralSectorType.EUROPE})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_country_clusters_action(self):
        """Test getting clusters for a country."""
        url = reverse('locations:country-clusters', kwargs={'pk': self.country.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['cluster_name'], 'London Cluster')


class ClusterLocationAPITest(BaseLocationAPITestCase):
    """Test ClusterLocation API endpoints."""
    
    def test_list_clusters(self):
        """Test listing clusters."""
        url = reverse('locations:cluster-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_cluster_detail(self):
        """Test retrieving cluster details."""
        url = reverse('locations:cluster-detail', kwargs={'pk': self.cluster.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['cluster_name'], 'London Cluster')
        self.assertIn('chapters', response.data)
        self.assertIn('leaders', response.data)
    
    def test_create_cluster_as_staff(self):
        """Test creating cluster as staff user."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('locations:cluster-list')
        data = {
            'cluster_name': 'Manchester Cluster',
            'cluster_code': 'MAN',
            'country': self.country.id,
            'description': 'Manchester area',
            'active': True
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['cluster_name'], 'Manchester Cluster')
    
    def test_filter_clusters_by_country(self):
        """Test filtering clusters by country."""
        url = reverse('locations:cluster-list')
        response = self.client.get(url, {'country': self.country.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_search_clusters(self):
        """Test searching clusters."""
        url = reverse('locations:cluster-list')
        response = self.client.get(url, {'search': 'London'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_cluster_chapters_action(self):
        """Test getting chapters for a cluster."""
        url = reverse('locations:cluster-chapters', kwargs={'pk': self.cluster.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)


class ChapterLocationAPITest(BaseLocationAPITestCase):
    """Test ChapterLocation API endpoints."""
    
    def test_list_chapters(self):
        """Test listing chapters."""
        url = reverse('locations:chapter-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_chapter_detail(self):
        """Test retrieving chapter details."""
        url = reverse('locations:chapter-detail', kwargs={'pk': self.chapter.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['chapter_name'], 'Central London')
        self.assertIn('areas', response.data)
        self.assertIn('leaders', response.data)
    
    def test_create_chapter_as_staff(self):
        """Test creating chapter as staff user."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('locations:chapter-list')
        data = {
            'chapter_name': 'North London',
            'chapter_code': 'NL',
            'cluster': self.cluster.id,
            'description': 'North London chapter',
            'active': True
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['chapter_name'], 'North London')
    
    def test_prevent_duplicate_chapter_in_cluster(self):
        """Test preventing duplicate chapter names in same cluster."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('locations:chapter-list')
        data = {
            'chapter_name': 'Central London',  # Already exists
            'chapter_code': 'CL2',
            'cluster': self.cluster.id,
            'description': 'Duplicate chapter',
            'active': True
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_chapter_areas_action(self):
        """Test getting areas for a chapter."""
        url = reverse('locations:chapter-areas', kwargs={'pk': self.chapter.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)


class AreaLocationAPITest(BaseLocationAPITestCase):
    """Test AreaLocation API endpoints."""
    
    def test_list_areas(self):
        """Test listing areas."""
        url = reverse('locations:area-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_area_detail(self):
        """Test retrieving area details."""
        url = reverse('locations:area-detail', kwargs={'pk': self.area.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['area_name'], 'Westminster')
        self.assertIn('relative_areas', response.data)
        self.assertIn('leaders', response.data)
        self.assertIn('area_id_str', response.data)
    
    def test_create_area_as_staff(self):
        """Test creating area as staff user."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('locations:area-list')
        data = {
            'area_name': 'Camden',
            'area_code': 'CM',
            'chapter': self.chapter.id,
            'description': 'Camden area',
            'active': True
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['area_name'], 'Camden')
    
    def test_search_areas_by_relative_area(self):
        """Test searching areas by relative area name."""
        url = reverse('locations:area-list')
        response = self.client.get(url, {'relative_search': 'Victoria'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        # Should find Westminster through Victoria relative area
        self.assertEqual(response.data['results'][0]['area_name'], 'Westminster')
    
    def test_filter_areas_by_chapter(self):
        """Test filtering areas by chapter."""
        url = reverse('locations:area-list')
        response = self.client.get(url, {'chapter': self.chapter.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_area_relative_areas_action(self):
        """Test getting relative areas for an area."""
        url = reverse('locations:area-relative-areas', kwargs={'pk': self.area.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Victoria')


class RelativeAreaAPITest(BaseLocationAPITestCase):
    """Test RelativeArea API endpoints."""
    
    def test_list_relative_areas(self):
        """Test listing relative areas."""
        url = reverse('locations:relativearea-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_relative_area_detail(self):
        """Test retrieving relative area details."""
        url = reverse('locations:relativearea-detail', kwargs={'pk': self.relative_area.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Victoria')
        self.assertIn('_links', response.data)
    
    def test_create_relative_area_as_staff(self):
        """Test creating relative area as staff user."""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse('locations:relativearea-list')
        data = {
            'name': 'Pimlico',
            'relative_area': self.area.id
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Pimlico')
    
    def test_search_relative_areas(self):
        """Test searching relative areas."""
        url = reverse('locations:relativearea-list')
        response = self.client.get(url, {'search': 'Victoria'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class POIAPITest(BaseLocationAPITestCase):
    """Test POI API endpoints."""
    
    def test_list_pois(self):
        """Test listing POIs."""
        url = reverse('locations:poi-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_poi_detail(self):
        """Test retrieving POI details."""
        url = reverse('locations:poi-detail', kwargs={'pk': self.poi.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Convention Centre')
        self.assertIn('latitude', response.data)
        self.assertIn('longitude', response.data)
    
    def test_create_poi_authenticated(self):
        """Test creating POI as authenticated user."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:poi-list')
        data = {
            'name': 'Community Hall',
            'description': 'Small community hall',
            'address': '456 High Street',
            'city': 'London',
            'postcode': 'E1 1AA',
            'poi_type': POITypeChoice.VENUE,
            'latitude': 51.5155,
            'longitude': -0.0922
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Community Hall')
    
    def test_create_poi_unauthenticated(self):
        """Test creating POI without authentication fails."""
        url = reverse('locations:poi-list')
        data = {
            'name': 'Test POI',
            'address': '789 Test St',
            'poi_type': POITypeChoice.VENUE
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_filter_pois_by_type(self):
        """Test filtering POIs by type."""
        url = reverse('locations:poi-list')
        response = self.client.get(url, {'poi_type': POITypeChoice.VENUE})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_pois_by_city(self):
        """Test filtering POIs by city."""
        url = reverse('locations:poi-list')
        response = self.client.get(url, {'city': 'London'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_search_pois(self):
        """Test searching POIs."""
        url = reverse('locations:poi-list')
        response = self.client.get(url, {'search': 'Convention'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class VenueAPITest(BaseLocationAPITestCase):
    """Test Venue API endpoints."""
    
    def test_list_venues(self):
        """Test listing venues."""
        url = reverse('locations:venue-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_venue_detail(self):
        """Test retrieving venue details."""
        url = reverse('locations:venue-detail', kwargs={'pk': self.venue.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['capacity'], 500)
        self.assertIn('poi_details', response.data)
        self.assertIn('rooms', response.data)
        self.assertIn('contacts', response.data)
    
    def test_create_venue_authenticated(self):
        """Test creating venue as authenticated user."""
        self.client.force_authenticate(user=self.regular_user)
        
        # Create a new POI first
        poi = POI.objects.create(
            name='New Venue Location',
            address='789 New Street',
            city='London',
            poi_type=POITypeChoice.VENUE,
            created_by=self.regular_user
        )
        
        url = reverse('locations:venue-list')
        data = {
            'poi': poi.id,
            'description': 'New venue',
            'capacity': 300
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['capacity'], 300)
    
    def test_prevent_duplicate_venue_for_poi(self):
        """Test preventing duplicate venues for same POI."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:venue-list')
        data = {
            'poi': self.poi.id,  # Already has a venue
            'description': 'Duplicate venue',
            'capacity': 100
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_venue_rooms_action(self):
        """Test getting rooms for a venue."""
        # Create a room first
        room = RoomVenue.objects.create(
            venue=self.venue,
            room_name='Hall A',
            capacity=100,
            added_by=self.regular_user
        )
        
        url = reverse('locations:venue-rooms', kwargs={'pk': self.venue.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)
    
    def test_venue_contacts_action(self):
        """Test getting contacts for a venue."""
        # Create a contact first
        contact = VenueContact.objects.create(
            venue=self.venue,
            contact_name='John Doe',
            email='john@example.com',
            role=VenueContactRoleChoice.MANAGER,
            added_by=self.regular_user
        )
        
        url = reverse('locations:venue-contacts', kwargs={'pk': self.venue.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)


class RoomVenueAPITest(BaseLocationAPITestCase):
    """Test RoomVenue API endpoints."""
    
    def setUp(self):
        super().setUp()
        self.room = RoomVenue.objects.create(
            venue=self.venue,
            room_name='Conference Room A',
            description='Large conference room',
            capacity=100,
            added_by=self.regular_user
        )
    
    def test_list_rooms(self):
        """Test listing room venues."""
        url = reverse('locations:room-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_room_detail(self):
        """Test retrieving room details."""
        url = reverse('locations:room-detail', kwargs={'pk': self.room.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['room_name'], 'Conference Room A')
        self.assertEqual(response.data['capacity'], 100)
    
    def test_create_room_authenticated(self):
        """Test creating room as authenticated user."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:room-list')
        data = {
            'venue': self.venue.id,
            'room_name': 'Meeting Room B',
            'description': 'Small meeting room',
            'capacity': 20
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['room_name'], 'Meeting Room B')
    
    def test_filter_rooms_by_venue(self):
        """Test filtering rooms by venue."""
        url = reverse('locations:room-list')
        response = self.client.get(url, {'venue': self.venue.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class VenueContactAPITest(BaseLocationAPITestCase):
    """Test VenueContact API endpoints."""
    
    def setUp(self):
        super().setUp()
        self.contact = VenueContact.objects.create(
            venue=self.venue,
            contact_name='Jane Smith',
            email='jane@example.com',
            phone_number='+441234567890',
            role=VenueContactRoleChoice.MANAGER,
            added_by=self.regular_user
        )
    
    def test_list_contacts(self):
        """Test listing venue contacts."""
        url = reverse('locations:venuecontact-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_contact_detail(self):
        """Test retrieving contact details."""
        url = reverse('locations:venuecontact-detail', kwargs={'pk': self.contact.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['contact_name'], 'Jane Smith')
        self.assertEqual(response.data['role'], VenueContactRoleChoice.MANAGER)
    
    def test_create_contact_authenticated(self):
        """Test creating contact as authenticated user."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:venuecontact-list')
        data = {
            'venue': self.venue.id,
            'contact_name': 'Bob Johnson',
            'email': 'bob@example.com',
            'role': VenueContactRoleChoice.OWNER
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['contact_name'], 'Bob Johnson')
    
    def test_filter_contacts_by_venue(self):
        """Test filtering contacts by venue."""
        url = reverse('locations:venuecontact-list')
        response = self.client.get(url, {'venue': self.venue.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_filter_contacts_by_role(self):
        """Test filtering contacts by role."""
        url = reverse('locations:venuecontact-list')
        response = self.client.get(url, {'role': VenueContactRoleChoice.MANAGER})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class VenueMetadataAPITest(BaseLocationAPITestCase):
    """Test VenueMetadata API endpoints."""
    
    def setUp(self):
        super().setUp()
        self.metadata = VenueMetadata.objects.create(
            venue=self.venue,
            poi=self.poi,
            label='Parking',
            value='200 spaces available',
            added_by=self.regular_user
        )
    
    def test_list_metadata(self):
        """Test listing venue metadata."""
        url = reverse('locations:venuemetadata-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_metadata_detail(self):
        """Test retrieving metadata details."""
        url = reverse('locations:venuemetadata-detail', kwargs={'pk': self.metadata.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['label'], 'Parking')
        self.assertEqual(response.data['value'], '200 spaces available')
    
    def test_create_metadata_authenticated(self):
        """Test creating metadata as authenticated user."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('locations:venuemetadata-list')
        data = {
            'venue': self.venue.id,
            'poi': self.poi.id,
            'label': 'WiFi',
            'value': 'Free high-speed WiFi available'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['label'], 'WiFi')
    
    def test_filter_metadata_by_venue(self):
        """Test filtering metadata by venue."""
        url = reverse('locations:venuemetadata-list')
        response = self.client.get(url, {'venue': self.venue.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class LeaderIntegrationAPITest(BaseLocationAPITestCase):
    """Test leader integration with location endpoints."""
    
    def setUp(self):
        super().setUp()
        
        # Create leader for area
        ct = ContentType.objects.get_for_model(AreaLocation)
        self.leader = Leader.objects.create(
            user=self.regular_user,
            target_type=ct,
            target_id=self.area.id,
            notes='Area leader',
            added_by=self.admin_user
        )
    
    def test_area_detail_includes_leader_info(self):
        """Test that area detail includes leader information."""
        url = reverse('locations:area-detail', kwargs={'pk': self.area.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('leaders', response.data)
        self.assertGreaterEqual(len(response.data['leaders']), 1)
        self.assertEqual(response.data['leaders'][0]['user_name'], self.regular_user.username)
        self.assertIn('_links', response.data['leaders'][0])
    
    def test_cluster_detail_includes_leader_info(self):
        """Test that cluster detail can include leader information."""
        ct = ContentType.objects.get_for_model(ClusterLocation)
        Leader.objects.create(
            user=self.staff_user,
            target_type=ct,
            target_id=self.cluster.id,
            notes='Cluster leader',
            added_by=self.admin_user
        )
        
        url = reverse('locations:cluster-detail', kwargs={'pk': self.cluster.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('leaders', response.data)
        self.assertGreaterEqual(len(response.data['leaders']), 1)


class HATEOASLinksAPITest(BaseLocationAPITestCase):
    """Test HATEOAS links in API responses."""
    
    def test_country_hateoas_links(self):
        """Test HATEOAS links in country response."""
        url = reverse('locations:country-detail', kwargs={'pk': self.country.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('clusters', response.data['_links'])
    
    def test_venue_hateoas_links(self):
        """Test HATEOAS links in venue response."""
        url = reverse('locations:venue-detail', kwargs={'pk': self.venue.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('poi', response.data['_links'])
        self.assertIn('rooms', response.data['_links'])
        self.assertIn('contacts', response.data['_links'])
    
    def test_area_hateoas_links(self):
        """Test HATEOAS links in area response."""
        url = reverse('locations:area-detail', kwargs={'pk': self.area.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('_links', response.data)
        self.assertIn('self', response.data['_links'])
        self.assertIn('chapter', response.data['_links'])
        self.assertIn('relative_areas', response.data['_links'])
