from .base import BasePersonalInfoModel, BaseAttendeePersonalInfoModel
from django.db import models

class SeverityLevel(models.TextChoices):
    MILD = 'mild', 'Mild'
    MODERATE = 'moderate', 'Moderate'
    SEVERE = 'severe', 'Severe'

class MedicalCondition(BasePersonalInfoModel):

    def __str__(self):
        return f"Medical Condition {self.label}"
    
    def __repr__(self):
        return f"<MedicalCondition {self.id} - {self.label}>"
    
class AttendeeMedicalCondition(BaseAttendeePersonalInfoModel): # m2m through model
    
    medical_condition = models.ForeignKey(MedicalCondition, on_delete=models.CASCADE, related_name='attendee_conditions')
    severity = models.CharField(max_length=100, null=True, blank=True, choices=SeverityLevel.choices)
    
    class Meta:
        unique_together = ('attendee', 'medical_condition')
    
    def __str__(self):
        return f"{self.medical_condition.label} for {self.attendee}"