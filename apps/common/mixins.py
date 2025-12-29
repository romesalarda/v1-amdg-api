from django.contrib.contenttypes.models import ContentType
from apps.common.models.resource import Resource
from apps.common.models.availability import AvailabilityWindow, AvailabilityTypeChoices

from django.core.exceptions import ValidationError

class HasResourceMixin:
    
    @property
    def resources(self):
        ct = ContentType.objects.get_for_model(self, for_concrete_model=False)
        return Resource.objects.filter(
            target_type=ct,
            target_id=self.pk,
        )
        
    def add_resource(self, resource: Resource):
        '''
        Adds a resource to the model instance.
        '''
        resource.target_id = self.id
        resource.target_type = ContentType.objects.get_for_model(self)
        resource.clean()
        resource.save()
        return resource
    
    def remove_resource(self, resource: Resource):
        '''
        Removes a resource from the model instance.
        '''
        if resource in self.resources:
            resource.delete()
            return True
        return False
    
class LandingImageMixin(HasResourceMixin):
    '''
    Mixin to add landing image functionality to a model.
    '''
    def add_landing_image(self, image_resource: Resource, is_main: bool = True):
        '''
        Adds a landing image resource to the model.
        '''
        if is_main:
            
            for existing_main in self.resources.filter(tag='LANDING_PHOTO_MAIN'):
                existing_main.tag = 'LANDING_PHOTO_SECONDARY'
                existing_main.save()
            image_resource.tag = 'LANDING_PHOTO_MAIN'
        else:
            image_resource.tag = 'LANDING_PHOTO_SECONDARY'
            
        return self.add_resource(image_resource)
    
    @property
    def landing_images(self):
        '''
        Returns landing image resources associated with this model.
        '''
        return self.resources.filter(tag__in=['LANDING_PHOTO_MAIN', 'LANDING_PHOTO_SECONDARY'])
    
    @property
    def main_landing_image(self):
        '''
        Returns the main landing image resource, if any.
        '''
        try:
            return self.resources.get(tag='LANDING_PHOTO_MAIN')
        except Resource.DoesNotExist:
            return None
        
    def clear_landing_images(self):
        '''
        Removes all landing image resources from this model.
        '''
        self.landing_images.delete()
        
class HasAvailabilityMixin:
    
    @property
    def availability_windows(self):
        ct = ContentType.objects.get_for_model(self, for_concrete_model=False)
        return AvailabilityWindow.objects.filter(
            target_type=ct,
            target_id=self.pk,
        )
        
    def add_availability_window(self, window: AvailabilityWindow): 
        '''
        Adds an availability window to the model instance.
        '''
        window.target_id = self.id
        window.target_type = ContentType.objects.get_for_model(self)
        window.clean()
        window.save()
        return window
    
    def remove_availability_window(self, window: AvailabilityWindow):
        '''
        Removes an availability window from the model instance.
        '''
        if window in self.availability_windows:
            window.delete()
            return True
        return False
    
    def is_within_availability_window(self, availability_type, check_datetime) -> bool:
        '''
        Checks if the given datetime is within the specified availability window type for this event.
        '''
        windows = self.availability_windows.filter(availability_type=availability_type)
        for window in windows:
            if window.within_window(check_datetime):
                return True
        return False    