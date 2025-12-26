from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Attendable(models.Model):
    
    check_in_time = models.DateTimeField(blank=True, null=True)
    check_out_time = models.DateTimeField(blank=True, null=True)
    check_in_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='checked_in_%(class)ss')
    check_out_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='checked_out_%(class)ss')

    class Meta:
        abstract = True
        ordering = ['-check_in_time']
        
    @property
    def is_checked_in(self):
        return self.check_in_time is not None and (self.check_out_time is None or self.check_out_time > self.check_in_time)
    
    @property
    def is_checked_out(self):
        return self.check_out_time is not None and (self.check_in_time is None or self.check_out_time > self.check_in_time)
    
    def check_in(self, time, by_user=None):
        self.check_in_time = time
        self.check_out_time = None
        self.check_in_by = by_user
        self.save()
        
    def check_out(self, time, by_user=None):
        self.check_out_time = time
        self.check_out_by = by_user
        self.save()
        
        