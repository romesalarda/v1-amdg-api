from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()

class HumanRelationshipChoices(models.TextChoices):
    PARENT = 'parent', 'Parent'
    SIBLING = 'sibling', 'Sibling'
    CHILD = 'child', 'Child'
    SPOUSE = 'spouse', 'Spouse'
    FRIEND = 'friend', 'Friend'
    OTHER = 'other', 'Other'

class FamilyGroup(models.Model):
    
    family_name = models.CharField(max_length=255)
    organisation = models.ForeignKey(
        'organisations.Organisation',
        on_delete=models.CASCADE,
        related_name='family_groups',
        null=True,
        blank=True,
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='family_groups',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='created_family_groups', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.event and self.organisation and self.event.organisation_id != self.organisation_id:
            raise ValidationError('Family group organisation must match the selected event organisation.')

    def save(self, *args, **kwargs):
        if self.event and not self.organisation_id:
            self.organisation = self.event.organisation
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.family_name
    
class FamilyAttendee(models.Model): # m2m through model
    
    family_group = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name='family_attendees')
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='family_groups')
    relationship = models.CharField(max_length=100, choices=HumanRelationshipChoices.choices)  # e.g., parent, sibling, child, etc.
    is_primary_guardian = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('family_group', 'attendee')
    
    def __str__(self):
        return f"{self.attendee} in {self.family_group} as {self.relationship}"