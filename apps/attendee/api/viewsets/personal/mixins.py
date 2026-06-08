from django.shortcuts import get_object_or_404
from apps.attendee.models import Attendee

class NestedAttendeeViewSetMixin:
    """
    Mixin to filter queryset by attendee_id from nested URL.
    
    For use with nested URLs like: /attendees/{attendee_id}/resource/
    """
    
    def get_attendee(self):
        """Get the parent attendee from the URL."""
        attendee_id = self.kwargs.get('attendee_id')
        if attendee_id:
            return get_object_or_404(Attendee, attendee_id=attendee_id, deleted_at__isnull=True)
        return None
    
    def get_queryset(self):
        """Filter queryset by attendee from URL parameters."""
        queryset = super().get_queryset()
        attendee = self.get_attendee()
        if attendee:
            queryset = queryset.filter(attendee=attendee)
        return queryset
    
    def perform_create(self, serializer):
        """Automatically set attendee on create."""
        attendee = self.get_attendee()
        if attendee:          
            serializer.save(attendee=attendee)
        else:
            serializer.save()