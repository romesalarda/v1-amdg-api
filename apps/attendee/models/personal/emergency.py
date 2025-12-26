from django.db import models
from django.core.validators import EmailValidator
from django.contrib.auth import get_user_model
from apps.common.models.verification import RequiresVerificationModel
from core.utils.validators import PhoneNumberValidator

User = get_user_model()

from apps.attendee.models.groups import HumanRelationshipChoices

class EmergencyContact(RequiresVerificationModel):
    
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='emergency_contacts')
    
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    relationship = models.CharField(max_length=50, 
                                    choices=HumanRelationshipChoices.choices, 
                                    default=HumanRelationshipChoices.OTHER
                                    )
    
    phone_number = models.CharField(max_length=20, validators=[PhoneNumberValidator()])
    email = models.EmailField(null=True, blank=True, validators=[EmailValidator()])
    primary_contact = models.BooleanField(default=False)
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='added_emergency_contacts', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.full_name} ({self.relationship}) for {self.attendee}"
    
    def __repr__(self):
        return f"<EmergencyContact {self.full_name} for Attendee {self.attendee.attendee_display_id}>"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"