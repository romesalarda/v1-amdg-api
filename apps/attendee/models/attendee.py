from django.db import models
from django.contrib.auth import get_user_model
from django.core import validators
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from core.utils.validators import PhoneNumberValidator
from core.utils import dates as date_validation, display 

from datetime import date
import uuid

from apps.locations.models import AreaLocation
from apps.payments.evaluator import DiscountContext

from apps.common.models.rules import AccessRule
from apps.common.evaluator import BaseEvaluator, BaseContext, rules_apply
from apps.common.models.softdelete import SoftDeleteModel

User = get_user_model()

class AttendeeRelationship(models.TextChoices):
    SELF = 'self', 'Self'
    SPOUSE = 'spouse', 'Spouse'
    CHILD = 'child', 'Child'
    FRIEND = 'friend', 'Friend'
    PARRENT = 'parent', 'Parent'
    SIBLING = 'sibling', 'Sibling'
    OTHER = 'other', 'Other'

class Attendee(SoftDeleteModel):
    
    attendee_id = models.UUIDField(default=uuid.uuid4, editable=False) # url-safe unique identifier
    attendee_display_id = models.CharField(max_length=100, unique=True, blank=True)  # human-readable unique identifier
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='attendees', null=True, blank=True)
    
    first_name = models.CharField(max_length=150, validators=[validators.MinLengthValidator(1)])
    last_name = models.CharField(max_length=150, validators=[validators.MinLengthValidator(1)])
    
    event = models.ForeignKey('events.Event', on_delete=models.SET_NULL, related_name='attendees', null=True, blank=True)
    
    email = models.EmailField(blank=True, null=True, validators=[validators.EmailValidator()])
    phone_number = models.CharField(max_length=20, null=True, blank=True, validators=[PhoneNumberValidator()])
    
    date_of_birth = models.DateField(null=True)
    gender = models.CharField(max_length=50, null=True, blank=True)
    
    relationship_to_user = models.CharField(
        max_length=20,
        choices=AttendeeRelationship.choices,
        default=AttendeeRelationship.SELF
    ) # relationship to the user who created this attendee
    
    booking = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL, related_name='attendees', null=True, blank=True) # a booking can have multiple attendees
    
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
        if self.gender:
            self.gender = self.gender.upper().strip()
        if not self.attendee_display_id:
            self.attendee_display_id = display.generate_human_readable_id(20, "ATT", self.event.display_code[:5])

        self.first_name = self.first_name.strip().title()
        self.last_name = self.last_name.strip().title()
        
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.full_name} ({self.attendee_display_id})"
    
    def __repr__(self):
        return f"<Attendee {self.attendee_display_id}: {self.full_name}>"
    
    def clean(self):        
        if self.date_of_birth and self.date_of_birth > date.today():
            raise ValidationError("Date of birth cannot be in the future.")
        
        if self.gender:
            if self.gender not in ['MALE', 'FEMALE', 'OTHER', 'PREFER_NOT_TO_SAY']:
                raise ValidationError("Invalid gender value.")
        
        if self.relationship_to_user == AttendeeRelationship.SELF and self.user is None:
            raise ValidationError("Attendees with 'self' relationship must be linked to a user account.")
        
        if self.date_of_birth is None:
            raise ValidationError("Date of birth is required for attendee.")
        
        if not self.event_id:
            raise ValidationError("Attendee must be linked to an event.")
        
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
    def is_event_staff(self):
        '''
        Determine if the attendee is event staff based on linked user account.
        '''
        return self.user and self.user.event_staff.filter(event=self.event).exists()
    
    @property
    def staff_role_names(self):
        '''
        Get a list of staff roles the attendee has for the event.
        '''
        if self.user:
            return list(self.user.event_roles.filter(event=self.event).values_list('role__name', flat=True))
        return []
    
    @property
    def was_defined_by_event_staff(self):
        '''
        Determine if the attendee was created by event staff.
        '''
        if self.defined_by:
            return self.defined_by.event_staff.filter(event=self.event).exists()
        return False
    
    @property
    def medical_conditions(self):
        from apps.attendee.models.personal.medical import AttendeeMedicalCondition
        return AttendeeMedicalCondition.objects.filter(attendee=self)
    
    @property
    def dietary_requirements(self):
        from apps.attendee.models.personal.dietary import AttendeeDietaryRequirement
        return AttendeeDietaryRequirement.objects.filter(attendee=self)
    
    @property
    def accessibility_requirements(self):
        from apps.attendee.models.personal.accessibility import AttendeeAccessibilityRequirement
        return AttendeeAccessibilityRequirement.objects.filter(attendee=self)   
    
    @property
    def consents(self):
        from apps.attendee.models.personal.consent import AttendeeConsent
        return AttendeeConsent.objects.filter(attendee=self)
    
    @property
    def self_registered(self): # means that this attendee can access dashboard, make decisions, etc.
        '''
        Determine if the attendee was self-registered (i.e., relationship is 'self').
        '''
        return self.relationship_to_user == AttendeeRelationship.SELF and self.user is not None
    
    @property
    def is_cancelled(self):
        '''
        Determine if the attendee has been marked as cancelled.
        '''
        return self.actions.filter(action=AttendeeActionChoices.CANCELLED).exists()
    
    @property
    def is_registered(self):
        '''
        Determine if the attendee has been marked as registered.
        '''
        return self.actions.filter(action=AttendeeActionChoices.REGISTERED).exists()
    
    def get_outstanding_payments(self):
        '''
        Retrieve a queryset of outstanding payments for this attendee.
        '''
        if not self.user:
            return Payment.objects.none()
        
        from apps.payments.models.payments import Payment, PaymentStatusChoices

        booking_oustanding = Payment.objects.filter(
            target_type=ContentType.objects.get_for_model(self.booking.__class__),
            target_id=self.booking.pk,
            status=PaymentStatusChoices.PENDING
        )
        
        return booking_oustanding
    
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
        latest_check_in = self.event_attendances.filter(event__isnull=False).order_by('-event__start_datetime')
        if latest_check_in.exists():
            latest_check_in = latest_check_in.first()
            return latest_check_in.is_checked_in
        return False
    
    @property
    def has_outstanding_payments(self):
        if not self.user: # only users with linked accounts can have payments
            return False
        # TODO: implement payment logic
        
    def pricing_context(self): # DEPRECATE in favour of get_base_context
        '''
        @param payable: An instance of a PayableModel (e.g., ticket, registration fee)
        @return: DiscountContext instance for pricing evaluations
        '''        
        return DiscountContext( #TODO migrate to use base from common
            user=self.user,
            event=self.event,
            metadata={
                "age": self.age,
                "organisations": list(self.organisations.values_list('organisation__title', flat=True)),
                "staff_roles": self.staff_role_names,
                "is_event_staff": self.is_event_staff,
                "full_name": self.full_name,
                "location": self.area_from.area_name if self.area_from else None,
            }
        )
    
    def get_base_context(self) -> BaseContext: # TODO: migrate to use common base context
        '''
        Generate a BaseContext for all evaluations.

        @return: BaseContext instance for rule evaluations
        '''
        return BaseContext(
            user=self.user,
            event=self.event,
            metadata={ # attendee-specific metadata
                "age": self.age,
                "organisations": list(self.organisations.values_list('organisation__title', flat=True)),
                "staff_roles": self.staff_role_names,
                "is_event_staff": self.is_event_staff,
                "full_name": self.full_name,
                "location": self.area_from.area_name if self.area_from else None,
            }
        )
        
    def add_organisation(self, organisation):
        '''
        Link an organisation to this attendee.
        '''
        from apps.attendee.models import AttendeeOrganisation
        link, created = AttendeeOrganisation.objects.get_or_create(
            attendee=self,
            organisation=organisation
        )
        return link
    
    def is_part_of_organisation(self, organisation):
        '''
        Check if the attendee is linked to a specific organisation.
        '''
        return self.organisations.filter(organisation=organisation).exists()
    
    def mark_checked_in(self, event, checked_in_by, raise_if_already_checked_in=False):
        
        from apps.attendee.models.personal.attendance import EventAttendance
        from apps.attendee.models import AttendeeAction, AttendeeActionChoices
        '''
        Mark the attendee as checked in for a specific event.
        '''
        attendance, created = EventAttendance.objects.get_or_create(
            event=event,
            attendee=self,
            defaults={'check_in_by': checked_in_by}
        )
        if not created:
            attendance.check_in_by = checked_in_by
            attendance.check_in_at = models.DateTimeField(auto_now=True)
            attendance.save()
            
        AttendeeAction.objects.create(
            action=AttendeeActionChoices.CHECKED_IN,
            attendee=self,
            performed_by=None # system action
        )
            
        if raise_if_already_checked_in and not created and attendance.is_checked_in:
            raise ValidationError("Attendee is already checked in for this event.")
        return attendance
    
    def mark_checked_out(self, event, checked_out_by=None, raise_if_not_checked_in=False):
        
        from apps.attendee.models.personal.attendance import EventAttendance
        from apps.attendee.models import AttendeeAction, AttendeeActionChoices

        '''
        Mark the attendee as checked out for a specific event.
        '''
        try:
            attendance = EventAttendance.objects.get(event=event, attendee=self)
            attendance.checked_out_by = checked_out_by
            attendance.checked_out_at = models.DateTimeField(auto_now=True)
            attendance.save()
            
            AttendeeAction.objects.create(
                action=AttendeeActionChoices.CHECKED_IN,
                attendee=self,
                performed_by=None # system action
            )   
        
            return attendance

        except EventAttendance.DoesNotExist:
            if raise_if_not_checked_in:
                raise ValidationError("Attendee is not checked in for this event.")
            return None
        
    def mark_registered(self, performed_by=None):
        '''
        Mark the attendee as registered.
        '''
        from apps.attendee.models import AttendeeAction, AttendeeActionChoices
        AttendeeAction.objects.create(
            action=AttendeeActionChoices.REGISTERED,
            attendee=self,
            performed_by=performed_by
        )
        
    def mark_cancelled(self, notes=None):
        '''
        Mark the attendee as cancelled.
        '''
        from apps.attendee.models import AttendeeAction, AttendeeActionChoices
        AttendeeAction.objects.create(
            action=AttendeeActionChoices.CANCELLED,
            attendee=self,
            performed_by=None, # system action,
            notes=notes
        )

    def get_metadata(self):
        '''
        Get metadata dictionary for this attendee.
        '''
        return {
            "attendee_id": str(self.attendee_id),
            "attendee_display_id": self.attendee_display_id,
            "full_name": self.full_name,
            "age": self.age,
            "relationship_to_user": self.relationship_to_user,
            "is_event_staff": self.is_event_staff,
            "staff_roles": self.staff_role_names,
            "added_at": self.created_at.isoformat(),
        }
    
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