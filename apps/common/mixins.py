from django.contrib.contenttypes.models import ContentType
from apps.common.models.resource import Resource
from apps.common.models.availability import AvailabilityWindow

class HasResourceMixin:
    
    @property
    def resources(self):
        ct = ContentType.objects.get_for_model(self, for_concrete_model=False)
        return Resource.objects.filter(
            target_type=ct,
            target_id=self.pk,
        )
        
class HasAvailabilityMixin:
    
    @property
    def availability_windows(self):
        ct = ContentType.objects.get_for_model(self, for_concrete_model=False)
        return AvailabilityWindow.objects.filter(
            target_type=ct,
            target_id=self.pk,
        )