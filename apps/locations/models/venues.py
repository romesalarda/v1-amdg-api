from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core import validators
from django.contrib.auth import get_user_model

from core.utils.validators import PhoneNumberValidator

User = get_user_model()

class POITypeChoice(models.TextChoices):
    
    ACCOMMODATION = 'ACCOMMODATION', 'Accommodation'
    VENUE = 'VENUE', 'Venue'
    SPORTS_VENUE = 'SPORTS_VENUE', 'Sports Venue'
    PUBLIC_TRANSPORT = 'PUBLIC_TRANSPORT', 'Public Transport'
    TRANSPORT = 'TRANSPORT', 'Transport'
    
class POI(models.Model): # only concerns locations
    '''
    Point of Interest (POI) model representing various types of locations.
    '''
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    address = models.TextField(max_length=500)
    postcode = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)
    poi_type = models.CharField(max_length=20, choices=POITypeChoice.choices)
    
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
        
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='venues_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='venues_updated')

    def __str__(self):
        return self.name
    
class Venue(models.Model):
    '''
    Venue model representing specific venues linked to POIs.
    '''
    poi = models.OneToOneField(POI, on_delete=models.CASCADE, related_name='venue')
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='venues_added')
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Venue: {self.poi.name}"
    
class RoomVenue(models.Model):
    '''
    RoomVenue model representing rooms within a venue.
    '''
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='rooms')
    room_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='room_venues_added')
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Room: {self.room_name} in Venue: {self.venue.poi.name}"
    
class VenueContactRoleChoice(models.TextChoices):
    MANAGER = 'MANAGER', 'Manager'
    OWNER = 'OWNER', 'Owner'
    COORDINATOR = 'COORDINATOR', 'Coordinator'
    SUPPORT = 'SUPPORT', 'Support'
    OTHER = 'OTHER', 'Other'
    
class VenueContact(models.Model):
    '''
    VenueContact model representing contact details for a venue.
    '''
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='contacts')
    contact_name = models.CharField(max_length=255, validators=[validators.MinLengthValidator(2)])
    phone_number = models.CharField(max_length=20, blank=True, null=True, validators=[PhoneNumberValidator()])
    email = models.EmailField(blank=True, null=True, validators=[validators.EmailValidator()])
    role = models.CharField(max_length=100, choices=VenueContactRoleChoice.choices, blank=True, default=VenueContactRoleChoice.OWNER)
    
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='venue_contacts_added')
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Contact: {self.contact_name} for Venue: {self.venue.poi.name}"
    
class VenueMetadata(models.Model):
    '''
    VenueMetadata model for storing additional metadata about a venue.
    '''
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='metadata')
    poi = models.ForeignKey(POI, on_delete=models.CASCADE, related_name='venue_metadata')
    label = models.CharField(max_length=255, verbose_name=_('Metadata Label'), help_text='Enter a label for the metadata. E.g. Distance from main venue')
    value = models.TextField(verbose_name=_('Metadata Value'), blank=True, null=True, help_text='Enter the metadata value here. E.g. 300M away from venue')
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='venue_metadata_added')
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Metadata: {self.label} for Venue: {self.venue.poi.name}"