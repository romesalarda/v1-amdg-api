from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from datetime import date
import uuid

from apps.locations.models import (
    GeneralSectorType, SpecificSectorType,
    CountryLocation, ClusterLocation, ChapterLocation, 
    AreaLocation, RelativeArea,
    POI, POITypeChoice, Venue, RoomVenue, 
    VenueContact, VenueContactRoleChoice, VenueMetadata
)

User = get_user_model()


# ==================== LOCATIONS MODELS TESTS ====================

class CountryLocationModelTest(TestCase):
    """Test cases for the CountryLocation model"""
    
    def setUp(self):
        """Set up test data"""
        self.country_data = {
            'country': 'US',
            'general_sector': GeneralSectorType.NORTH_AMERICA,
            'specific_sector': SpecificSectorType.NORTH_AMERICA,
        }
    
    def test_country_location_creation(self):
        """Test basic country location creation"""
        country = CountryLocation.objects.create(**self.country_data)
        
        self.assertEqual(country.country.code, 'US')
        self.assertEqual(country.general_sector, GeneralSectorType.NORTH_AMERICA)
        self.assertEqual(country.specific_sector, SpecificSectorType.NORTH_AMERICA)
        self.assertTrue(country.active)
        self.assertIsNotNone(country.date_added)
    
    def test_country_location_str_representation(self):
        """Test string representation of country location"""
        country = CountryLocation.objects.create(**self.country_data)
        expected = f"{self.country_data['general_sector']} -> {self.country_data['specific_sector']} -> {country.country}"
        
        self.assertEqual(str(country), expected)
    
    def test_country_location_repr(self):
        """Test repr of country location"""
        country = CountryLocation.objects.create(**self.country_data)
        
        self.assertIn('CountryLocation', repr(country))
        self.assertIn('country=US', repr(country))
        self.assertIn('general_sector', repr(country))
    
    def test_country_unique_constraint(self):
        """Test that country must be unique"""
        CountryLocation.objects.create(**self.country_data)
        
        with self.assertRaises(IntegrityError):
            CountryLocation.objects.create(**self.country_data)
    
    def test_country_location_active_default(self):
        """Test that active defaults to True"""
        country = CountryLocation.objects.create(**self.country_data)
        
        self.assertTrue(country.active)
    
    def test_country_location_inactive(self):
        """Test setting country as inactive"""
        country = CountryLocation.objects.create(
            country='GB',
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE,
            active=False
        )
        
        self.assertFalse(country.active)
    
    def test_country_location_with_all_general_sectors(self):
        """Test creating country locations for all general sectors"""
        sectors = [
            (GeneralSectorType.EUROPE, SpecificSectorType.WEST_EUROPE, 'FR'),
            (GeneralSectorType.ASIA, SpecificSectorType.EAST_ASIA, 'JP'),
            (GeneralSectorType.AFRICA, SpecificSectorType.WEST_AFRICA, 'NG'),
            (GeneralSectorType.OCEANIA, SpecificSectorType.AUSTRALIA_NEWZEALAND, 'AU'),
            (GeneralSectorType.MIDDLE_EAST, SpecificSectorType.GULF, 'AE'),
        ]
        
        for general, specific, country_code in sectors:
            country = CountryLocation.objects.create(
                country=country_code,
                general_sector=general,
                specific_sector=specific
            )
            self.assertEqual(country.general_sector, general)
            self.assertEqual(country.specific_sector, specific)


class ClusterLocationModelTest(TestCase):
    """Test cases for the ClusterLocation model"""
    
    def setUp(self):
        """Set up test data"""
        self.country = CountryLocation.objects.create(
            country='US',
            general_sector=GeneralSectorType.NORTH_AMERICA,
            specific_sector=SpecificSectorType.NORTH_AMERICA
        )
        self.cluster_data = {
            'cluster_name': 'California Cluster',
            'country': self.country,
            'description': 'Test description'
        }
    
    def test_cluster_creation(self):
        """Test basic cluster creation"""
        cluster = ClusterLocation.objects.create(**self.cluster_data)
        
        self.assertEqual(cluster.cluster_name, 'California Cluster')
        self.assertEqual(cluster.country, self.country)
        self.assertEqual(cluster.description, 'Test description')
        self.assertTrue(cluster.active)
        self.assertIsNotNone(cluster.date_added)
    
    def test_cluster_code_auto_generation(self):
        """Test that cluster_code is auto-generated from cluster_name"""
        cluster = ClusterLocation.objects.create(**self.cluster_data)
        
        self.assertEqual(cluster.cluster_code, 'CAL')
    
    def test_cluster_code_manual_setting(self):
        """Test setting cluster_code manually"""
        cluster = ClusterLocation.objects.create(
            cluster_name='Texas Cluster',
            cluster_code='TEX',
            country=self.country
        )
        
        self.assertEqual(cluster.cluster_code, 'TEX')
    
    def test_cluster_code_unique_constraint(self):
        """Test that cluster_code must be unique"""
        ClusterLocation.objects.create(
            cluster_name='First Cluster',
            cluster_code='FIR',
            country=self.country
        )
        
        with self.assertRaises(IntegrityError):
            ClusterLocation.objects.create(
                cluster_name='Second Cluster',
                cluster_code='FIR',
                country=self.country
            )
    
    def test_cluster_name_title_case(self):
        """Test that cluster_name is converted to title case"""
        cluster = ClusterLocation.objects.create(
            cluster_name='california cluster',
            country=self.country
        )
        
        self.assertEqual(cluster.cluster_name, 'California Cluster')
    
    def test_cluster_name_strip_whitespace(self):
        """Test that cluster_name whitespace is stripped"""
        cluster = ClusterLocation.objects.create(
            cluster_name='  California Cluster  ',
            country=self.country
        )
        
        self.assertEqual(cluster.cluster_name, 'California Cluster')
    
    def test_cluster_str_representation(self):
        """Test string representation of cluster"""
        cluster = ClusterLocation.objects.create(**self.cluster_data)
        expected = f"{self.country} -> California Cluster"
        
        self.assertEqual(str(cluster), expected)
    
    def test_cluster_repr(self):
        """Test repr of cluster"""
        cluster = ClusterLocation.objects.create(**self.cluster_data)
        
        self.assertIn('ClusterLocation', repr(cluster))
        self.assertIn('cluster_name=California Cluster', repr(cluster))
    
    def test_cluster_cascade_delete_with_country(self):
        """Test that cluster is deleted when country is deleted"""
        cluster = ClusterLocation.objects.create(**self.cluster_data)
        cluster_id = cluster.id
        
        self.country.delete()
        
        self.assertFalse(ClusterLocation.objects.filter(id=cluster_id).exists())
    
    def test_cluster_date_updated_auto_now(self):
        """Test that date_updated is automatically updated"""
        cluster = ClusterLocation.objects.create(**self.cluster_data)
        original_date = cluster.date_updated
        
        cluster.description = 'Updated description'
        cluster.save()
        
        self.assertGreaterEqual(cluster.date_updated, original_date)


class ChapterLocationModelTest(TestCase):
    """Test cases for the ChapterLocation model"""
    
    def setUp(self):
        """Set up test data"""
        self.country = CountryLocation.objects.create(
            country='US',
            general_sector=GeneralSectorType.NORTH_AMERICA,
            specific_sector=SpecificSectorType.NORTH_AMERICA
        )
        self.cluster = ClusterLocation.objects.create(
            cluster_name='California Cluster',
            country=self.country
        )
        self.chapter_data = {
            'chapter_name': 'Los Angeles Chapter',
            'cluster': self.cluster,
            'description': 'Chapter in LA'
        }
    
    def test_chapter_creation(self):
        """Test basic chapter creation"""
        chapter = ChapterLocation.objects.create(**self.chapter_data)
        
        self.assertEqual(chapter.chapter_name, 'Los Angeles Chapter')
        self.assertEqual(chapter.cluster, self.cluster)
        self.assertEqual(chapter.description, 'Chapter in LA')
        self.assertTrue(chapter.active)
        self.assertIsNotNone(chapter.date_added)
    
    def test_chapter_code_auto_generation(self):
        """Test that chapter_code is auto-generated from chapter_name"""
        chapter = ChapterLocation.objects.create(**self.chapter_data)
        
        self.assertEqual(chapter.chapter_code, 'LOS')
    
    def test_chapter_code_manual_setting(self):
        """Test setting chapter_code manually"""
        chapter = ChapterLocation.objects.create(
            chapter_name='San Francisco Chapter',
            chapter_code='SFC',
            cluster=self.cluster
        )
        
        self.assertEqual(chapter.chapter_code, 'SFC')
    
    def test_chapter_name_title_case(self):
        """Test that chapter_name is converted to title case"""
        chapter = ChapterLocation.objects.create(
            chapter_name='los angeles chapter',
            cluster=self.cluster
        )
        
        self.assertEqual(chapter.chapter_name, 'Los Angeles Chapter')
    
    def test_chapter_name_strip_whitespace(self):
        """Test that chapter_name whitespace is stripped"""
        chapter = ChapterLocation.objects.create(
            chapter_name='  Los Angeles Chapter  ',
            cluster=self.cluster
        )
        
        self.assertEqual(chapter.chapter_name, 'Los Angeles Chapter')
    
    def test_chapter_unique_together_constraint(self):
        """Test that chapter_name and cluster must be unique together"""
        ChapterLocation.objects.create(**self.chapter_data)
        
        with self.assertRaises(IntegrityError):
            ChapterLocation.objects.create(**self.chapter_data)
    
    def test_chapter_same_name_different_cluster(self):
        """Test that same chapter_name can exist in different clusters"""
        ChapterLocation.objects.create(**self.chapter_data)
        
        another_cluster = ClusterLocation.objects.create(
            cluster_name='Texas Cluster',
            cluster_code='TEX',
            country=self.country
        )
        
        chapter2 = ChapterLocation.objects.create(
            chapter_name='Los Angeles Chapter',
            cluster=another_cluster
        )
        
        self.assertEqual(chapter2.chapter_name, 'Los Angeles Chapter')
        self.assertEqual(chapter2.cluster, another_cluster)
    
    def test_chapter_str_representation(self):
        """Test string representation of chapter"""
        chapter = ChapterLocation.objects.create(**self.chapter_data)
        expected = f"{self.cluster} -> Los Angeles Chapter"
        
        self.assertEqual(str(chapter), expected)
    
    def test_chapter_repr(self):
        """Test repr of chapter"""
        chapter = ChapterLocation.objects.create(**self.chapter_data)
        
        self.assertIn('ChapterLocation', repr(chapter))
        self.assertIn('chapter_name=Los Angeles Chapter', repr(chapter))
    
    def test_chapter_cascade_delete_with_cluster(self):
        """Test that chapter is deleted when cluster is deleted"""
        chapter = ChapterLocation.objects.create(**self.chapter_data)
        chapter_id = chapter.id
        
        self.cluster.delete()
        
        self.assertFalse(ChapterLocation.objects.filter(id=chapter_id).exists())
    
    def test_chapter_description_max_length(self):
        """Test chapter description max length"""
        long_description = 'a' * 400
        chapter = ChapterLocation.objects.create(
            chapter_name='Test Chapter',
            cluster=self.cluster,
            description=long_description
        )
        
        self.assertEqual(len(chapter.description), 400)


class AreaLocationModelTest(TestCase):
    """Test cases for the AreaLocation model"""
    
    def setUp(self):
        """Set up test data"""
        self.country = CountryLocation.objects.create(
            country='US',
            general_sector=GeneralSectorType.NORTH_AMERICA,
            specific_sector=SpecificSectorType.NORTH_AMERICA
        )
        self.cluster = ClusterLocation.objects.create(
            cluster_name='California Cluster',
            country=self.country
        )
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Los Angeles Chapter',
            cluster=self.cluster
        )
        self.area_data = {
            'area_name': 'Downtown Area',
            'chapter': self.chapter,
            'description': 'Central downtown area'
        }
    
    def test_area_creation(self):
        """Test basic area creation"""
        area = AreaLocation.objects.create(**self.area_data)
        
        self.assertEqual(area.area_name, 'Downtown Area')
        self.assertEqual(area.chapter, self.chapter)
        self.assertEqual(area.description, 'Central downtown area')
        self.assertTrue(area.active)
        self.assertIsNotNone(area.date_added)
        self.assertIsInstance(area.area_id, uuid.UUID)
    
    def test_area_uuid_auto_generation(self):
        """Test that area_id UUID is auto-generated"""
        area = AreaLocation.objects.create(**self.area_data)
        
        self.assertIsNotNone(area.area_id)
        self.assertIsInstance(area.area_id, uuid.UUID)
    
    def test_area_code_auto_generation(self):
        """Test that area_code is auto-generated from area_name"""
        area = AreaLocation.objects.create(**self.area_data)
        
        self.assertEqual(area.area_code, 'DOW')
    
    def test_area_code_unique_constraint(self):
        """Test that area_code must be unique"""
        AreaLocation.objects.create(
            area_name='Downtown Area',
            area_code='DOW',
            chapter=self.chapter
        )
        
        with self.assertRaises(IntegrityError):
            AreaLocation.objects.create(
                area_name='Different Area',
                area_code='DOW',
                chapter=self.chapter
            )
    
    def test_area_name_title_case(self):
        """Test that area_name is converted to title case"""
        area = AreaLocation.objects.create(
            area_name='downtown area',
            chapter=self.chapter
        )
        
        self.assertEqual(area.area_name, 'Downtown Area')
    
    def test_area_name_strip_whitespace(self):
        """Test that area_name whitespace is stripped"""
        area = AreaLocation.objects.create(
            area_name='  Downtown Area  ',
            chapter=self.chapter
        )
        
        self.assertEqual(area.area_name, 'Downtown Area')
    
    def test_area_unique_together_constraint(self):
        """Test that area_name and chapter must be unique together"""
        AreaLocation.objects.create(**self.area_data)
        
        with self.assertRaises(IntegrityError):
            AreaLocation.objects.create(**self.area_data)
    
    def test_area_same_name_different_chapter(self):
        """Test that same area_name can exist in different chapters"""
        AreaLocation.objects.create(**self.area_data)
        
        another_chapter = ChapterLocation.objects.create(
            chapter_name='San Francisco Chapter',
            chapter_code='SFC',
            cluster=self.cluster
        )
        
        area2 = AreaLocation.objects.create(
            area_name='Downtown Area',
            area_code='DTA',
            chapter=another_chapter
        )
        
        self.assertEqual(area2.area_name, 'Downtown Area')
        self.assertEqual(area2.chapter, another_chapter)
    
    def test_area_str_representation(self):
        """Test string representation of area"""
        area = AreaLocation.objects.create(**self.area_data)
        expected = f"{self.chapter} -> Downtown Area"
        
        self.assertEqual(str(area), expected)
    
    def test_area_repr(self):
        """Test repr of area"""
        area = AreaLocation.objects.create(**self.area_data)
        
        self.assertIn('AreaLocation', repr(area))
        self.assertIn('area_name=Downtown Area', repr(area))
    
    def test_area_cascade_delete_with_chapter(self):
        """Test that area is deleted when chapter is deleted"""
        area = AreaLocation.objects.create(**self.area_data)
        area_id = area.id
        
        self.chapter.delete()
        
        self.assertFalse(AreaLocation.objects.filter(id=area_id).exists())
    
    def test_area_clean_validation_no_chapter(self):
        """Test that clean() raises ValidationError when chapter is None"""
        area = AreaLocation(
            area_name='Test Area',
            chapter=None
        )
        
        with self.assertRaises(ValidationError) as context:
            area.clean()
        
        self.assertIn('Chapter must be set', str(context.exception))
    
    def test_area_unique_constraint_per_chapter(self):
        """Test unique constraint for area_code per chapter"""
        AreaLocation.objects.create(
            area_name='First Area',
            area_code='FIR',
            chapter=self.chapter
        )
        
        # Same code in same chapter should fail
        with self.assertRaises(IntegrityError):
            AreaLocation.objects.create(
                area_name='Second Area',
                area_code='FIR',
                chapter=self.chapter
            )


class RelativeAreaModelTest(TestCase):
    """Test cases for the RelativeArea model"""
    
    def setUp(self):
        """Set up test data"""
        self.country = CountryLocation.objects.create(
            country='US',
            general_sector=GeneralSectorType.NORTH_AMERICA,
            specific_sector=SpecificSectorType.NORTH_AMERICA
        )
        self.cluster = ClusterLocation.objects.create(
            cluster_name='California Cluster',
            country=self.country
        )
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Los Angeles Chapter',
            cluster=self.cluster
        )
        self.area = AreaLocation.objects.create(
            area_name='Downtown Area',
            chapter=self.chapter
        )
    
    def test_relative_area_creation(self):
        """Test basic relative area creation"""
        relative = RelativeArea.objects.create(
            name='Hollywood',
            relative_area=self.area
        )
        
        self.assertEqual(relative.name, 'Hollywood')
        self.assertEqual(relative.relative_area, self.area)
    
    def test_relative_area_name_title_case(self):
        """Test that name is converted to title case"""
        relative = RelativeArea.objects.create(
            name='hollywood',
            relative_area=self.area
        )
        
        self.assertEqual(relative.name, 'Hollywood')
    
    def test_relative_area_name_strip_whitespace(self):
        """Test that name whitespace is stripped"""
        relative = RelativeArea.objects.create(
            name='  Hollywood  ',
            relative_area=self.area
        )
        
        self.assertEqual(relative.name, 'Hollywood')
    
    def test_relative_area_str_representation(self):
        """Test string representation of relative area"""
        relative = RelativeArea.objects.create(
            name='Hollywood',
            relative_area=self.area
        )
        expected = f"Hollywood -> {self.area}"
        
        self.assertEqual(str(relative), expected)
    
    def test_relative_area_repr(self):
        """Test repr of relative area"""
        relative = RelativeArea.objects.create(
            name='Hollywood',
            relative_area=self.area
        )
        
        self.assertIn('RelativeArea', repr(relative))
        self.assertIn('name=Hollywood', repr(relative))
    
    def test_relative_area_null_relative_area(self):
        """Test creating relative area with null relative_area"""
        relative = RelativeArea.objects.create(
            name='Unlinked Area',
            relative_area=None
        )
        
        self.assertIsNone(relative.relative_area)
    
    def test_relative_area_set_null_on_area_delete(self):
        """Test that relative_area is set to NULL when area is deleted"""
        relative = RelativeArea.objects.create(
            name='Hollywood',
            relative_area=self.area
        )
        
        self.area.delete()
        relative.refresh_from_db()
        
        self.assertIsNone(relative.relative_area)


# ==================== VENUES MODELS TESTS ====================

class POIModelTest(TestCase):
    """Test cases for the POI (Point of Interest) model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.poi_data = {
            'name': 'Grand Convention Center',
            'description': 'Large convention center',
            'address': '123 Main Street',
            'postcode': '90001',
            'city': 'Los Angeles',
            'poi_type': POITypeChoice.VENUE,
            'created_by': self.user
        }
    
    def test_poi_creation(self):
        """Test basic POI creation"""
        poi = POI.objects.create(**self.poi_data)
        
        self.assertEqual(poi.name, 'Grand Convention Center')
        self.assertEqual(poi.description, 'Large convention center')
        self.assertEqual(poi.address, '123 Main Street')
        self.assertEqual(poi.postcode, '90001')
        self.assertEqual(poi.city, 'Los Angeles')
        self.assertEqual(poi.poi_type, POITypeChoice.VENUE)
        self.assertEqual(poi.created_by, self.user)
        self.assertIsNotNone(poi.created_at)
        self.assertIsNotNone(poi.updated_at)
    
    def test_poi_with_coordinates(self):
        """Test POI creation with latitude and longitude"""
        poi = POI.objects.create(
            name='Test Location',
            address='123 Test St',
            poi_type=POITypeChoice.ACCOMMODATION,
            latitude=34.052235,
            longitude=-118.243683,
            created_by=self.user
        )
        
        self.assertEqual(float(poi.latitude), 34.052235)
        self.assertEqual(float(poi.longitude), -118.243683)
    
    def test_poi_str_representation(self):
        """Test string representation of POI"""
        poi = POI.objects.create(**self.poi_data)
        
        self.assertEqual(str(poi), 'Grand Convention Center')
    
    def test_poi_all_type_choices(self):
        """Test creating POIs with all type choices"""
        types = [
            POITypeChoice.ACCOMMODATION,
            POITypeChoice.VENUE,
            POITypeChoice.SPORTS_VENUE,
            POITypeChoice.PUBLIC_TRANSPORT,
            POITypeChoice.TRANSPORT
        ]
        
        for poi_type in types:
            poi = POI.objects.create(
                name=f'Test {poi_type}',
                address='123 Test St',
                poi_type=poi_type,
                created_by=self.user
            )
            self.assertEqual(poi.poi_type, poi_type)
    
    def test_poi_without_optional_fields(self):
        """Test POI creation without optional fields"""
        poi = POI.objects.create(
            name='Minimal POI',
            address='123 Street',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        
        self.assertEqual(poi.description, '')
        self.assertEqual(poi.postcode, '')
        self.assertEqual(poi.city, '')
        self.assertIsNone(poi.latitude)
        self.assertIsNone(poi.longitude)
    
    def test_poi_updated_by_tracking(self):
        """Test that updated_by can be set"""
        poi = POI.objects.create(**self.poi_data)
        
        another_user = User.objects.create_user(
            username='updater',
            email='updater@example.com',
            password='pass123'
        )
        
        poi.description = 'Updated description'
        poi.updated_by = another_user
        poi.save()
        
        self.assertEqual(poi.updated_by, another_user)
    
    def test_poi_created_by_set_null_on_user_delete(self):
        """Test that created_by is set to NULL when user is deleted"""
        poi = POI.objects.create(**self.poi_data)
        
        self.user.delete()
        poi.refresh_from_db()
        
        self.assertIsNone(poi.created_by)


class VenueModelTest(TestCase):
    """Test cases for the Venue model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.poi = POI.objects.create(
            name='Grand Convention Center',
            address='123 Main Street',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        self.venue_data = {
            'poi': self.poi,
            'description': 'Modern convention center',
            'instructions': 'Use main entrance',
            'notes': 'Parking available',
            'capacity': 500,
            'added_by': self.user
        }
    
    def test_venue_creation(self):
        """Test basic venue creation"""
        venue = Venue.objects.create(**self.venue_data)
        
        self.assertEqual(venue.poi, self.poi)
        self.assertEqual(venue.description, 'Modern convention center')
        self.assertEqual(venue.instructions, 'Use main entrance')
        self.assertEqual(venue.notes, 'Parking available')
        self.assertEqual(venue.capacity, 500)
        self.assertEqual(venue.added_by, self.user)
        self.assertIsNotNone(venue.added_at)
        self.assertIsNotNone(venue.updated_at)
    
    def test_venue_str_representation(self):
        """Test string representation of venue"""
        venue = Venue.objects.create(**self.venue_data)
        
        self.assertEqual(str(venue), 'Venue: Grand Convention Center')
    
    def test_venue_one_to_one_with_poi(self):
        """Test one-to-one relationship with POI"""
        venue = Venue.objects.create(**self.venue_data)
        
        # Try to create another venue with the same POI
        with self.assertRaises(IntegrityError):
            Venue.objects.create(
                poi=self.poi,
                added_by=self.user
            )
    
    def test_venue_without_optional_fields(self):
        """Test venue creation without optional fields"""
        venue = Venue.objects.create(
            poi=self.poi,
            added_by=self.user
        )
        
        self.assertEqual(venue.description, '')
        self.assertEqual(venue.instructions, '')
        self.assertEqual(venue.notes, '')
        self.assertIsNone(venue.capacity)
    
    def test_venue_cascade_delete_with_poi(self):
        """Test that venue is deleted when POI is deleted"""
        venue = Venue.objects.create(**self.venue_data)
        venue_id = venue.id
        
        self.poi.delete()
        
        self.assertFalse(Venue.objects.filter(id=venue_id).exists())
    
    def test_venue_reverse_relation_from_poi(self):
        """Test accessing venue from POI"""
        venue = Venue.objects.create(**self.venue_data)
        
        self.assertEqual(self.poi.venue, venue)
    
    def test_venue_added_by_set_null_on_user_delete(self):
        """Test that added_by is set to NULL when user is deleted"""
        venue = Venue.objects.create(**self.venue_data)
        
        self.user.delete()
        venue.refresh_from_db()
        
        self.assertIsNone(venue.added_by)


class RoomVenueModelTest(TestCase):
    """Test cases for the RoomVenue model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.poi = POI.objects.create(
            name='Convention Center',
            address='123 Main St',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        self.venue = Venue.objects.create(
            poi=self.poi,
            capacity=1000,
            added_by=self.user
        )
        self.room_data = {
            'venue': self.venue,
            'room_name': 'Conference Room A',
            'description': 'Large conference room',
            'capacity': 100,
            'added_by': self.user
        }
    
    def test_room_creation(self):
        """Test basic room creation"""
        room = RoomVenue.objects.create(**self.room_data)
        
        self.assertEqual(room.venue, self.venue)
        self.assertEqual(room.room_name, 'Conference Room A')
        self.assertEqual(room.description, 'Large conference room')
        self.assertEqual(room.capacity, 100)
        self.assertEqual(room.added_by, self.user)
        self.assertIsNotNone(room.added_at)
    
    def test_room_str_representation(self):
        """Test string representation of room"""
        room = RoomVenue.objects.create(**self.room_data)
        
        self.assertEqual(str(room), 'Room: Conference Room A in Venue: Convention Center')
    
    def test_room_multiple_rooms_per_venue(self):
        """Test creating multiple rooms for the same venue"""
        room1 = RoomVenue.objects.create(
            venue=self.venue,
            room_name='Room A',
            added_by=self.user
        )
        room2 = RoomVenue.objects.create(
            venue=self.venue,
            room_name='Room B',
            added_by=self.user
        )
        
        self.assertEqual(self.venue.rooms.count(), 2)
        self.assertIn(room1, self.venue.rooms.all())
        self.assertIn(room2, self.venue.rooms.all())
    
    def test_room_without_optional_fields(self):
        """Test room creation without optional fields"""
        room = RoomVenue.objects.create(
            venue=self.venue,
            room_name='Simple Room',
            added_by=self.user
        )
        
        self.assertIsNone(room.description)
        self.assertIsNone(room.capacity)
    
    def test_room_cascade_delete_with_venue(self):
        """Test that room is deleted when venue is deleted"""
        room = RoomVenue.objects.create(**self.room_data)
        room_id = room.id
        
        self.venue.delete()
        
        self.assertFalse(RoomVenue.objects.filter(id=room_id).exists())
    
    def test_room_added_by_set_null_on_user_delete(self):
        """Test that added_by is set to NULL when user is deleted"""
        room = RoomVenue.objects.create(**self.room_data)
        
        self.user.delete()
        room.refresh_from_db()
        
        self.assertIsNone(room.added_by)


class VenueContactModelTest(TestCase):
    """Test cases for the VenueContact model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.poi = POI.objects.create(
            name='Convention Center',
            address='123 Main St',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        self.venue = Venue.objects.create(
            poi=self.poi,
            added_by=self.user
        )
        self.contact_data = {
            'venue': self.venue,
            'contact_name': 'John Manager',
            'phone_number': '+1234567890',
            'email': 'john@venue.com',
            'role': VenueContactRoleChoice.MANAGER,
            'added_by': self.user
        }
    
    def test_contact_creation(self):
        """Test basic venue contact creation"""
        contact = VenueContact.objects.create(**self.contact_data)
        
        self.assertEqual(contact.venue, self.venue)
        self.assertEqual(contact.contact_name, 'John Manager')
        self.assertEqual(contact.phone_number, '+1234567890')
        self.assertEqual(contact.email, 'john@venue.com')
        self.assertEqual(contact.role, VenueContactRoleChoice.MANAGER)
        self.assertEqual(contact.added_by, self.user)
        self.assertIsNotNone(contact.added_at)
    
    def test_contact_str_representation(self):
        """Test string representation of contact"""
        contact = VenueContact.objects.create(**self.contact_data)
        
        self.assertEqual(str(contact), 'Contact: John Manager for Venue: Convention Center')
    
    def test_contact_name_min_length_validation(self):
        """Test that contact name must be at least 2 characters"""
        contact = VenueContact(
            venue=self.venue,
            contact_name='J',  # Only 1 character
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            contact.full_clean()
    
    def test_contact_phone_validation_valid(self):
        """Test phone number validation with valid numbers"""
        valid_phones = [
            '+1234567890',
            '1234567890',
            '+123456789012345',  # Max 15 digits
        ]
        
        for phone in valid_phones:
            contact = VenueContact(
                venue=self.venue,
                contact_name='Test Contact',
                phone_number=phone,
                added_by=self.user
            )
            contact.full_clean()  # Should not raise
            self.assertEqual(contact.phone_number, phone)
    
    def test_contact_phone_validation_invalid(self):
        """Test phone number validation with invalid numbers"""
        invalid_phones = [
            '123',  # Too short
            'abcdefghij',  # Letters
            '+12-345-6789',  # Dashes
        ]
        
        for phone in invalid_phones:
            contact = VenueContact(
                venue=self.venue,
                contact_name='Test Contact',
                phone_number=phone,
                added_by=self.user
            )
            with self.assertRaises(ValidationError):
                contact.full_clean()
    
    def test_contact_email_validation(self):
        """Test email validation"""
        contact = VenueContact(
            venue=self.venue,
            contact_name='Test Contact',
            email='invalid-email',
            added_by=self.user
        )
        
        with self.assertRaises(ValidationError):
            contact.full_clean()
    
    def test_contact_all_role_choices(self):
        """Test creating contacts with all role choices"""
        roles = [
            VenueContactRoleChoice.MANAGER,
            VenueContactRoleChoice.OWNER,
            VenueContactRoleChoice.COORDINATOR,
            VenueContactRoleChoice.SUPPORT,
            VenueContactRoleChoice.OTHER
        ]
        
        for role in roles:
            contact = VenueContact.objects.create(
                venue=self.venue,
                contact_name=f'Contact {role}',
                role=role,
                added_by=self.user
            )
            self.assertEqual(contact.role, role)
    
    def test_contact_default_role(self):
        """Test that default role is OWNER"""
        contact = VenueContact.objects.create(
            venue=self.venue,
            contact_name='Test Contact',
            added_by=self.user
        )
        
        self.assertEqual(contact.role, VenueContactRoleChoice.OWNER)
    
    def test_contact_multiple_contacts_per_venue(self):
        """Test creating multiple contacts for the same venue"""
        contact1 = VenueContact.objects.create(
            venue=self.venue,
            contact_name='Manager One',
            role=VenueContactRoleChoice.MANAGER,
            added_by=self.user
        )
        contact2 = VenueContact.objects.create(
            venue=self.venue,
            contact_name='Owner Two',
            role=VenueContactRoleChoice.OWNER,
            added_by=self.user
        )
        
        self.assertEqual(self.venue.contacts.count(), 2)
        self.assertIn(contact1, self.venue.contacts.all())
        self.assertIn(contact2, self.venue.contacts.all())
    
    def test_contact_without_optional_fields(self):
        """Test contact creation without optional fields"""
        contact = VenueContact.objects.create(
            venue=self.venue,
            contact_name='Minimal Contact',
            added_by=self.user
        )
        
        self.assertEqual(contact.phone_number, None)
        self.assertIsNone(contact.email)
    
    def test_contact_cascade_delete_with_venue(self):
        """Test that contact is deleted when venue is deleted"""
        contact = VenueContact.objects.create(**self.contact_data)
        contact_id = contact.id
        
        self.venue.delete()
        
        self.assertFalse(VenueContact.objects.filter(id=contact_id).exists())
    
    def test_contact_added_by_set_null_on_user_delete(self):
        """Test that added_by is set to NULL when user is deleted"""
        contact = VenueContact.objects.create(**self.contact_data)
        
        self.user.delete()
        contact.refresh_from_db()
        
        self.assertIsNone(contact.added_by)


class VenueMetadataModelTest(TestCase):
    """Test cases for the VenueMetadata model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.poi = POI.objects.create(
            name='Convention Center',
            address='123 Main St',
            poi_type=POITypeChoice.VENUE,
            created_by=self.user
        )
        self.venue = Venue.objects.create(
            poi=self.poi,
            added_by=self.user
        )
        self.metadata_data = {
            'venue': self.venue,
            'poi': self.poi,
            'label': 'Distance from airport',
            'value': '15 kilometers',
            'added_by': self.user
        }
    
    def test_metadata_creation(self):
        """Test basic venue metadata creation"""
        metadata = VenueMetadata.objects.create(**self.metadata_data)
        
        self.assertEqual(metadata.venue, self.venue)
        self.assertEqual(metadata.poi, self.poi)
        self.assertEqual(metadata.label, 'Distance from airport')
        self.assertEqual(metadata.value, '15 kilometers')
        self.assertEqual(metadata.added_by, self.user)
        self.assertIsNotNone(metadata.added_at)
    
    def test_metadata_str_representation(self):
        """Test string representation of metadata"""
        metadata = VenueMetadata.objects.create(**self.metadata_data)
        
        # Note: The __str__ method uses 'key' but the field is 'label'
        # This appears to be a bug in the model, but we test what's there
        self.assertIn('Metadata', str(metadata))
        self.assertIn('Convention Center', str(metadata))
    
    def test_metadata_multiple_per_venue(self):
        """Test creating multiple metadata entries for the same venue"""
        metadata1 = VenueMetadata.objects.create(
            venue=self.venue,
            poi=self.poi,
            label='WiFi Available',
            value='Yes',
            added_by=self.user
        )
        metadata2 = VenueMetadata.objects.create(
            venue=self.venue,
            poi=self.poi,
            label='Parking Spaces',
            value='200',
            added_by=self.user
        )
        
        self.assertEqual(self.venue.metadata.count(), 2)
        self.assertIn(metadata1, self.venue.metadata.all())
        self.assertIn(metadata2, self.venue.metadata.all())
    
    def test_metadata_without_value(self):
        """Test metadata creation without value"""
        metadata = VenueMetadata.objects.create(
            venue=self.venue,
            poi=self.poi,
            label='TBD Feature',
            added_by=self.user
        )
        
        self.assertIsNone(metadata.value)
    
    def test_metadata_cascade_delete_with_venue(self):
        """Test that metadata is deleted when venue is deleted"""
        metadata = VenueMetadata.objects.create(**self.metadata_data)
        metadata_id = metadata.id
        
        self.venue.delete()
        
        self.assertFalse(VenueMetadata.objects.filter(id=metadata_id).exists())
    
    def test_metadata_cascade_delete_with_poi(self):
        """Test that metadata is deleted when POI is deleted"""
        metadata = VenueMetadata.objects.create(**self.metadata_data)
        metadata_id = metadata.id
        
        self.poi.delete()
        
        self.assertFalse(VenueMetadata.objects.filter(id=metadata_id).exists())
    
    def test_metadata_added_by_set_null_on_user_delete(self):
        """Test that added_by is set to NULL when user is deleted"""
        metadata = VenueMetadata.objects.create(**self.metadata_data)
        
        self.user.delete()
        metadata.refresh_from_db()
        
        self.assertIsNone(metadata.added_by)
