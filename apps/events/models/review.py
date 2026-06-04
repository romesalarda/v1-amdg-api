from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth import get_user_model

User = get_user_model()

class EventReview(models.Model):
    '''
    Model representing reviews for events.
    '''
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_reviews', null=True, blank=True)
    
    rating = models.PositiveIntegerField(help_text="Rating for the event, on a scale of 1 to 5.",
                                            validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True, null=True, help_text="Optional comment about the event.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    approved = models.BooleanField(default=False, help_text="Whether the review has been approved by an organiser or admin.")
    is_public = models.BooleanField(default=True, help_text="Whether the review is visible to others.")

    @property
    def is_anonymous(self):
        return self.user is None
    
    def __str__(self):
        if self.is_anonymous:
            return f"Anonymous review for {self.event} - Rating: {self.rating}"
        return f"Review by {self.user} for {self.event} - Rating: {self.rating}"