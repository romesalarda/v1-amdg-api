from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError
from core.utils.validators import PhoneNumberValidator
from core.utils import dates as date_validation, display 

from datetime import date
import uuid

from apps.locations.models import AreaLocation

User = get_user_model()

class AttendeeRelationship(models.TextChoices):
    SELF = 'self', 'Self'
    SPOUSE = 'spouse', 'Spouse'
    CHILD = 'child', 'Child'
    FRIEND = 'friend', 'Friend'
    OTHER = 'other', 'Other'

class Attendee(models.Model):
    
    attendee_id = models.UUIDField(default=uuid.uuid4, editable=False) # url-safe unique identifier
    attendee_display_id = models.CharField(max_length=100, unique=True, blank=True)  # human-readable unique identifier
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='attendees', null=True, blank=True)
    
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    
    event = models.ForeignKey('events.Event', on_delete=models.SET_NULL, related_name='attendees', null=True, blank=True)
    
    email = models.EmailField(blank=True, null=True, validators=[EmailValidator()])
    phone_number = models.CharField(max_length=20, null=True, blank=True, validators=[PhoneNumberValidator()])
    
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=50, null=True, blank=True)
    
    relationship_to_user = models.CharField(
        max_length=20,
        choices=AttendeeRelationship.choices,
        default=AttendeeRelationship.SELF
    ) # relationship to the user who created this attendee
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    defined_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='created_attendees', null=True, blank=True)
    
    area_from = models.ForeignKey(AreaLocation, on_delete=models.SET_NULL, related_name='attendees_from', null=True, blank=True)
    
    class Meta:
        verbose_name = "Attendee"
        verbose_name_plural = "Attendees"
        
        indexes = [
            models.Index(fields=['attendee_id']),
            models.Index(fields=['attendee_display_id']),
            models.Index(fields=['email']),
        ]
        
    def save(self, *args, **kwargs):
        if not self.attendee_display_id:
            self.attendee_display_id = display.generate_human_readable_id(max_length=20, prefix="ATT", args=(self.event.display_code[:5],))
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.attendee_display_id})"
    
    def __repr__(self):
        return f"<Attendee {self.attendee_display_id}: {self.full_name}>"
    
    def clean(self):
        super().clean()
        
        if self.relationship_to_user == AttendeeRelationship.SELF and self.user is None:
            raise ValidationError("Attendees with 'self' relationship must be linked to a user account.")
        
        self.first_name = self.first_name.strip().title()
        self.last_name = self.last_name.strip().title()
        
        if not date_validation.valid_date_of_birth(self.date_of_birth, raise_exception=False):
            raise ValidationError("Date of birth cannot be in the future or unreasonably far in the past.")
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def age(self):
        if self.date_of_birth:
            today = date.today()
            return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        return None
    
    @property
    def is_minor(self):
        age = self.age
        if age is not None:
            return age < 18
        return None
    
    @property
    def self_registered(self): # means that this attendee can access dashboard, make decisions, etc.
        '''
        Determine if the attendee was self-registered (i.e., relationship is 'self').
        '''
        return self.relationship_to_user == AttendeeRelationship.SELF and self.user is not None
    
    def latest_action(self):
        '''
        Retrieve the latest action performed on this attendee.
        '''
        return self.actions.order_by('-performed_at').first()
    
    @property
    def is_checked_in(self):
        '''
        Determine if the attendee is currently checked in based on their latest event attendance.
        '''
        latest_check_in = self.event_attendances.filter(event__isnull=False).order_by('-event__start_date')
        if latest_check_in.exists():
            latest_check_in = latest_check_in.first()
            return latest_check_in.is_checked_in
        return False
    
    @property
    def has_outstanding_payments(self):
        if not self.user: # only users with linked accounts can have payments
            return False
        # TODO: implement payment logic
    
    def mark_checked_in(self, event, checked_in_by=None, raise_if_already_checked_in=False):
        
        from apps.attendee.models.personal.attendance import EventAttendance
        '''
        Mark the attendee as checked in for a specific event.
        '''
        attendance, created = EventAttendance.objects.get_or_create(
            event=event,
            attendee=self,
            defaults={'checked_in_by': checked_in_by}
        )
        if not created:
            attendance.checked_in_by = checked_in_by
            attendance.checked_in_at = models.DateTimeField(auto_now=True)
            attendance.save()
            
        if raise_if_already_checked_in and not created and attendance.is_checked_in:
            raise ValidationError("Attendee is already checked in for this event.")
        return attendance
    
    def mark_checked_out(self, event, checked_out_by=None, raise_if_not_checked_in=False):
        
        from apps.attendee.models.personal.attendance import EventAttendance
        '''
        Mark the attendee as checked out for a specific event.
        '''
        try:
            attendance = EventAttendance.objects.get(event=event, attendee=self)
            attendance.checked_out_by = checked_out_by
            attendance.checked_out_at = models.DateTimeField(auto_now=True)
            attendance.save()
            return attendance
        except EventAttendance.DoesNotExist:
            if raise_if_not_checked_in:
                raise ValidationError("Attendee is not checked in for this event.")
            return None
    
class AttendeeGuardian(models.Model):
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='guarded_attendees', null=True, blank=True)
    attendee = models.ForeignKey(Attendee, on_delete=models.CASCADE, related_name='guardians')
    relationship = models.CharField(max_length=100, choices=AttendeeRelationship.choices)
    added_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user} is guardian of {self.attendee} as {self.relationship}"
    
    def __repr__(self):
        return f"<AttendeeGuardian: {self.user} -> {self.attendee} ({self.relationship})>"
    
class AttendeeActionChoices(models.TextChoices):
    REGISTERED = 'registered', 'Registered'
    CHECKED_IN = 'checked_in', 'Checked In'
    CANCELLED = 'cancelled', 'Cancelled'
    UPDATED_INFO = 'updated_info', 'Updated Information'
    
class AttendeeAction(models.Model): # used to track actions on attendees
    '''
    Log of actions performed on an Attendee record.
    '''
    action = models.CharField(max_length=50, choices=AttendeeActionChoices.choices, default=AttendeeActionChoices.REGISTERED)
    attendee = models.ForeignKey(Attendee, on_delete=models.CASCADE, related_name='actions')
    performed_by = models.ForeignKey(Attendee, on_delete=models.SET_NULL, related_name='performed_attendee_actions', null=True, blank=True)
    performed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(null=True, blank=True)
    
    def __str__(self):
        return f"Action {self.action} on {self.attendee} at {self.performed_at}"
    
    def __repr__(self):
        return f"<AttendeeAction: {self.action} on {self.attendee} by {self.performed_by}>"