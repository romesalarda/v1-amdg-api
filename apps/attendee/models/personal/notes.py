from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model


class AttendeeNote(models.Model):
    '''
    Represents a note associated with an attendee. 
    '''
    
    attendee = models.ForeignKey(
        "attendee.Attendee",
        on_delete=models.CASCADE,
        related_name="notes",
    )
    note = models.TextField(max_length=1000, verbose_name=_("Note"))
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_attendee_notes",
    )

    def __str__(self):
        return f"Note for {self.attendee} by {self.created_by}"
    
    class Meta:
        verbose_name = _("Attendee Note")
        verbose_name_plural = _("Attendee Notes")
        ordering = ['-created_at']