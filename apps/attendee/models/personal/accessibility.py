from django.db import models
from .base import BasePersonalInfoModel, BaseAttendeePersonalInfoModel
from django.contrib.auth import get_user_model

User = get_user_model()

class AccessibilityRequirement(BasePersonalInfoModel):

    def __str__(self):
        return f"Accessibility Requirement {self.label}"
    
    def __repr__(self):
        return f"<AccessibilityRequirement {self.id} - {self.label}>"
    
class AttendeeAccessibilityRequirement(BaseAttendeePersonalInfoModel): # m2m through model
    
    accessibility_requirement = models.ForeignKey(AccessibilityRequirement, on_delete=models.CASCADE, related_name='attendee_requirements')
    
    class Meta:
        unique_together = ('attendee', 'accessibility_requirement')
    
    def __str__(self):
        return f"{self.accessibility_requirement} for {self.attendee}"