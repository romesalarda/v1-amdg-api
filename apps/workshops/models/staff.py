from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from apps.common.models import RequiresVerificationModel

class WorkshopStaffRoleChoice(models.TextChoices):
    INSTRUCTOR = 'INSTRUCTOR', _('Instructor')
    ASSISTANT = 'ASSISTANT', _('Assistant')
    LEADER = 'LEADER', _('Leader')
    OTHER = 'OTHER', _('Other')

class WorkshopStaff(RequiresVerificationModel):

    '''
    Represents a staff member associated with a workshop, along with their role.
    '''
    
    workshop = models.ForeignKey("workshops.Workshop", on_delete=models.CASCADE, related_name="staff_members")
    event_staff = models.ForeignKey("events.EventStaff", on_delete=models.CASCADE, related_name="workshop_staff_roles")
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, related_name='workshop_staff_added')
    role = models.CharField(max_length=20, choices=WorkshopStaffRoleChoice.choices, default=WorkshopStaffRoleChoice.OTHER)
    notes = models.TextField(blank=True, null=True, help_text=_("Additional notes about the staff member's role or responsibilities for the workshop"))

    def __str__(self):
        return f"{self.event_staff} ({self.get_role_display()}) - {self.workshop.title}"
    
    class Meta:
        verbose_name = _("Workshop Staff")
        verbose_name_plural = _("Workshop Staff")
        unique_together = ('workshop', 'event_staff')  # Prevent duplicate staff assignments to the same workshop


    def clean(self):
        # Ensure that the event staff member is associated with the same event as the workshop
        if self.event_staff and self.workshop and self.event_staff.event != self.workshop.event:
            raise ValidationError(_("Event staff member must be associated with the same event as the workshop."))