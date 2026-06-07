from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from apps.common.models import RequiresVerificationModel
from apps.payments.mixins import PayableModel

User = get_user_model()

# create an option, define a general schedule, then add stops for that schedule. 
# This allows for flexible transport options that can accommodate shuttles, parking information, public transit details, and more.

class TransportType(models.TextChoices):

    SHUTTLE = 'shuttle', 'Shuttle Service'
    PARKING = 'parking', 'Parking Information'
    PUBLIC_TRANSIT = 'public_transit', 'Public Transit Information'
    BUS_SHUTTLE = 'bus_shuttle', 'Bus Shuttle Service'
    CAR_SHARING = 'car_sharing', 'Car Sharing Information'
    CAR_SHUTTLE = 'car_shuttle', 'Car Shuttle Service'
    BIKE_SHARING = 'bike_sharing', 'Bike Sharing Information'
    OTHER = 'other', 'Other'

class EventTransportOption(PayableModel):
    '''
    Model representing transport options for an event. This can include details about transportation provided by the event, such as shuttles, parking, or public transit information.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='transport_options')
    name = models.CharField(max_length=255, help_text="Name of the transport option (e.g., 'Shuttle Service', 'Parking', 'Public Transit').")
    transport_type = models.CharField(max_length=50, choices=TransportType.choices, help_text="Type of transport option.")

    description = models.TextField(blank=True, null=True, help_text="Detailed information about the transport option.")
    is_provided_by_event = models.BooleanField(default=False, help_text="Whether this transport option is provided by the event itself.")
    contact_info = models.CharField(max_length=255, blank=True, null=True, help_text="Contact information for this transport option (e.g., shuttle service contact number).")
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_transport_options'
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_transport_type_display()} for {self.event.name}"
    
    def __repr__(self):
        return f"<EventTransportOption {self.get_transport_type_display()} for {self.event.name}>"
    
    def clean(self):
        super().clean()
        if self.is_provided_by_event and not self.contact_info:
            raise ValidationError({'contact_info': 'Contact information must be provided if the transport option is provided by the event.'})

class EventTransportSchedule(RequiresVerificationModel):
    '''
    Model representing the schedule for a transport option. This can include details about the timing and frequency of shuttles, parking availability, or public transit schedules.
    '''
    transport_option = models.ForeignKey(EventTransportOption, on_delete=models.CASCADE, related_name='schedules')
    start_datetime = models.DateTimeField(help_text="Date and time of the transport service (e.g., shuttle pickup date and time).")
    end_datetime = models.DateTimeField(help_text="Estimated arrival date and time for the transport service.")

    frequency_minutes = models.PositiveIntegerField(help_text="Frequency of the transport option in minutes (e.g., shuttle every 30 minutes).")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_transport_schedules'
    )
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def day_of_week(self):
        return self.start_datetime.strftime('%A')
    
    @property
    def start_time(self):
        return self.start_datetime.strftime('%H:%M')
    
    @property
    def end_time(self):
        return self.end_datetime.strftime('%H:%M')

    @property
    def duration_minutes(self):
        return int((self.end_datetime - self.start_datetime).total_seconds() / 60)

    def __str__(self):
        return f"Schedule for {self.transport_option} on {self.day_of_week}"
    
    def __repr__(self): 
        return f"<EventTransportSchedule for {self.transport_option} on {self.day_of_week}>"
    
    def clean(self):
        super().clean()
        if self.end_datetime <= self.start_datetime:
            raise ValidationError({'end_datetime': 'End date and time must be after start date and time.'})
class EventTransportStop(models.Model):
    '''
    Model representing stops for a transport option. This can include details about the locations where shuttles will stop, parking areas, or public transit stops.
    '''
    transport_option = models.ForeignKey(EventTransportOption, on_delete=models.CASCADE, related_name='stops')
    stop_name = models.CharField(max_length=255, help_text="Name of the transport stop (e.g., 'Main Entrance Shuttle Stop', 'Parking Lot A').")
    
    pickup_location = models.ForeignKey(
        'locations.POI',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transport_pickup_location',
        help_text="Point of Interest (POI) associated with this transport schedule (e.g., shuttle pickup location)."
    )

    pickup_instructions = models.TextField(blank=True, null=True, help_text="Instructions for the pickup location (e.g., 'Shuttle pickup at the main entrance of the venue').")

    arrival_datetime = models.DateTimeField(help_text="Estimated arrival date and time at this stop.")
    departure_datetime = models.DateTimeField(help_text="Estimated departure date and time from this stop.")
    
    instructions = models.TextField(blank=True, null=True, help_text="Instructions for this transport stop (e.g., 'Shuttle will stop here every 30 minutes').")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_transport_stops'
    )
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def stop_duration_minutes(self):
        return int((self.departure_datetime - self.arrival_datetime).total_seconds() / 60)

    def __str__(self):
        return f"{self.stop_name} for {self.transport_option}"
    
    def __repr__(self):
        return f"<EventTransportStop {self.stop_name} for {self.transport_option}>"
    
    def clean(self):
        super().clean()
        if self.departure_datetime <= self.arrival_datetime:
            raise ValidationError({'departure_datetime': 'Departure date and time must be after arrival date and time.'})
    
