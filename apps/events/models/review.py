from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class EventReview(models.Model):
    '''
    Model representing reviews for events.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_reviews')
    
    rating = models.PositiveIntegerField()
    comment = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    approved = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Review by {self.user} for {self.event} - Rating: {self.rating}"