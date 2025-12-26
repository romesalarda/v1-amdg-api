from django.db import models

from apps.common.models.attendance import Attendable

class EventAttendance(Attendable):
    
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='attendances')
    attendee = models.ForeignKey('attendee.Attendee', on_delete=models.CASCADE, related_name='event_attendances')
    
    class Meta:
        unique_together = ('event', 'attendee')
    
    def __str__(self):
        return f"Attendance of {self.attendee} for {self.event}"

