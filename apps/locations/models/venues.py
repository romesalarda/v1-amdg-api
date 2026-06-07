from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core import validators
from django.core.exceptions import ValidationError
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
    
    def __repr__(self):
        return f"<POI {self.name} ({self.get_poi_type_display()})>"
    
    def clean(self):
        super().clean()
        if self.latitude is not None and (self.latitude < -90 or self.latitude > 90):
            raise ValidationError({'latitude': 'Latitude must be between -90 and 90 degrees.'})
        if self.longitude is not None and (self.longitude < -180 or self.longitude > 180):
            raise ValidationError({'longitude': 'Longitude must be between -180 and 180 degrees.'})
    
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
    
    def __repr__(self):
        return f"<Venue {self.poi.name}>"
        
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
    
    def __repr__(self):
        return f"<RoomVenue {self.room_name} in Venue: {self.venue.poi.name}>"
        
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


# ============================================================================
# FLOOR PLAN MODELS
# ============================================================================

class FloorPlan(models.Model):
    """
    Floor plan image for a venue, representing a single level/floor.

    Images are stored via the configured storage backend (S3 in production,
    local MEDIA_ROOT in development). Pixel dimensions are extracted server-side
    on upload using Pillow — never trust client-supplied values.
    """

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name='floor_plans')
    event_venue = models.ForeignKey('events.EventVenue', on_delete=models.SET_NULL, null=True, blank=True, related_name='floor_plans', help_text='Optional link to an EventVenue snapshot for historical reference')
    name = models.CharField(max_length=255)
    level = models.PositiveIntegerField(default=0, help_text='0 = ground floor, increment upward')
    level_label = models.CharField(max_length=100, blank=True, help_text='Optional human-readable label, e.g. "Mezzanine"')
    image = models.ImageField(upload_to='floor_plans/')
    original_width = models.PositiveIntegerField(help_text='Pixel width of the uploaded image, extracted server-side')
    original_height = models.PositiveIntegerField(help_text='Pixel height of the uploaded image, extracted server-side')

    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='floor_plans_added')
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['level', 'name']

    def __str__(self):
        label = f' ({self.level_label})' if self.level_label else ''
        return f"Floor Plan: {self.name} — Level {self.level}{label} — {self.venue.poi.name}"
    
    def __repr__(self):
        return f"<FloorPlan {self.name} for Venue: {self.venue.poi.name}>"
    
    def clean(self):
        super().clean()
        if self.original_width <= 0:
            raise ValidationError({'original_width': 'Original width must be a positive integer.'})
        if self.original_height <= 0:
            raise ValidationError({'original_height': 'Original height must be a positive integer.'})


class FloorPlanAnnotation(models.Model):
    """
    Polygon annotation drawn on a floor plan image.

    Vertices are stored as a JSON array of normalised {x, y} objects where both
    coordinates are floats in the range [0.0, 1.0] relative to the image dimensions.
    The frontend is responsible for converting between pixel space and normalised space.
    """

    floor_plan = models.ForeignKey(FloorPlan, on_delete=models.CASCADE, related_name='annotations')
    room_venue = models.ForeignKey(
        'events.EventVenueRoom', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='floor_plan_annotations',
        help_text='Optional link to an existing room in this venue',
    )
    label = models.CharField(max_length=255)
    colour = models.CharField(
        max_length=20, default='#4F46E5',
        help_text='Hex colour string used for rendering the polygon on the canvas',
    )
    vertices = models.JSONField(
        help_text='List of {x: float, y: float} normalised coordinate objects (min 3 points)',
    )

    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='floor_plan_annotations_added')
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Annotation: {self.label} on {self.floor_plan.name}"
    
    def clean(self):
        super().clean()
        if not isinstance(self.vertices, list) or len(self.vertices) < 3:
            raise ValidationError({'vertices': 'At least 3 vertices are required to form a polygon.'})
        for vertex in self.vertices:
            if 'x' not in vertex or 'y' not in vertex:
                raise ValidationError({'vertices': 'Each vertex must be an object with "x" and "y" properties.'})
            if not (0.0 <= vertex['x'] <= 1.0) or not (0.0 <= vertex['y'] <= 1.0):
                raise ValidationError({'vertices': 'Vertex coordinates must be normalised floats between 0.0 and 1.0.'})


class FloorPlanAnnotationMetadata(models.Model):
    """
    Arbitrary key-value metadata attached to a floor plan annotation.

    Separate from VenueMetadata — scoped specifically to an annotation polygon
    rather than the venue as a whole.
    """

    annotation = models.ForeignKey(FloorPlanAnnotation, on_delete=models.CASCADE, related_name='metadata')
    label = models.CharField(max_length=255)
    value = models.TextField(blank=True)

    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='floor_plan_annotation_metadata_added')
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Metadata: {self.label} on annotation '{self.annotation.label}'"
    
    def __repr__(self):
        return f"<FloorPlanAnnotationMetadata {self.label} on annotation '{self.annotation.label}'>"
