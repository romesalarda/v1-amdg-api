from django.db import models
from django.contrib.auth import get_user_model

from .base import BaseAttendeePersonalInfoModel, BasePersonalInfoModel

User = get_user_model()

class DietaryRequirement(BasePersonalInfoModel):

    def __str__(self):
        return f"Dietary Requirement {self.label}"
    
    def __repr__(self):
        return f"<DietaryRequirement {self.id} - {self.label}>"
    
class AttendeeDietaryRequirement(BaseAttendeePersonalInfoModel): # m2m through model
    
    dietary_requirement = models.ForeignKey(DietaryRequirement, on_delete=models.CASCADE, related_name='attendee_requirements')
    
    class Meta:
        unique_together = ('attendee', 'dietary_requirement')
    
    def __str__(self):
        return f"{self.dietary_requirement.label} for {self.attendee}"