from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.core import exceptions
from django.contrib.auth import get_user_model
from django.conf import settings

from apps.common.mixins import HasResourceMixin, HasAvailabilityMixin, HasRuleMixin
from apps.common.models.resource import Resource

from datetime import datetime

class ProductMixin (HasResourceMixin, HasAvailabilityMixin, HasRuleMixin):
    '''
    Shared mixin for models that involve payments, providing common properties and methods.
    Images are marked as resources with tags 'PRODUCT_PHOTO_MAIN' and 'PRODUCT_PHOTO_SECONDARY'.
    '''
    @property
    def requires_verification(self):
        '''
        Returns whether the product requires verification before purchase.
        '''
        return self.event.settings.product_publication_requires_verification
    
    @property
    def can_publish(self):
        '''
        Returns whether the product can be published (made active).
        '''
        if self.requires_verification and not self.verified:
            return False
        return True
    
    @property
    def is_purchasable(self):
        '''
        Returns whether the product is purchasable based on its active status and availability windows.
        '''
        if not self.is_active:
            return False
        
        now = datetime.now()
        availability_windows = self.product_availability_windows
        if availability_windows.exists():
            for window in availability_windows:
                if window.available_from <= now <= window.available_to:
                    return True
            return False
        return True
    
    @property
    def product_availability_windows(self):
        '''
        Returns availability windows specific to this product.
        '''
        from apps.common.models.availability import AvailabilityTypeChoices
        return self.availability_windows.filter(availability_type=AvailabilityTypeChoices.PRODUCT)
    
    @property
    def product_images(self):
        '''
        Returns product image resources associated with this product.
        '''
        return self.resources.filter(tag__in=['PRODUCT_PHOTO_MAIN', 'PRODUCT_PHOTO_SECONDARY'])
    
    def add_product_image(self, image_resource: Resource, is_main: bool = True):
        '''
        Adds a product image resource to the product.

        @param image_resource: The Resource instance representing the image.
        @param is_main: Whether this image should be marked as the main product image.
        Returns the added Resource instance.
        '''

        if not image_resource.is_image:
            raise exceptions.ValidationError("The provided resource is not an image.")

        if is_main:
            for existing_main in self.resources.filter(tag='PRODUCT_PHOTO_MAIN'):
                existing_main.tag = 'PRODUCT_PHOTO_SECONDARY'
                existing_main.save()
            image_resource.tag = 'PRODUCT_PHOTO_MAIN'
        else:
            image_resource.tag = 'PRODUCT_PHOTO_SECONDARY'
        
        return self.add_resource(image_resource)
    
    def remove_product_image(self, image_resource: Resource):
        '''
        Removes a product image resource from the product.

        @param image_resource: The Resource instance representing the image to remove.
        '''
        if image_resource not in self.resources.all():
            raise exceptions.ValidationError("The provided resource is not associated with this product.")
        
        self.remove_resource(image_resource)
    
    def add_availability_window(self, start_datetime: datetime, end_datetime: datetime, timezone=None):
        '''
        Adds a product-specific availability window. I.e. the product is only available for purchase within this window.
        Raises ValidationError if the window clashes with existing windows.

        @param start_datetime: The start datetime of the availability window.
        @param end_datetime: The end datetime of the availability window.
        @param timezone: The timezone for the availability window. If None, defaults to event's default timezone or system timezone.
        Returns the created AvailabilityWindow instance.

        '''
        from apps.common.models.availability import AvailabilityTypeChoices, AvailabilityWindow

        if timezone is None:
            timezone = self.event.settings.default_timezone if self.event.settings.default_timezone else settings.TIME_ZONE

        if start_datetime >= end_datetime:
            raise exceptions.ValidationError("start_datetime must be earlier than end_datetime")
        
        # if one clashes
        existing_windows = self.product_availability_windows
        for window in existing_windows:
            if not (end_datetime <= window.available_from or start_datetime >= window.available_to):
                raise exceptions.ValidationError("The new availability window clashes with an existing window.")

        aw = AvailabilityWindow(
            name=f"Product Availability for {self.title}",
            availability_type=AvailabilityTypeChoices.PRODUCT,
            target_type=ContentType.objects.get_for_model(self),
            target=self,
            available_from=start_datetime,
            available_to=end_datetime,
            timezone=timezone
        )
        aw.clean()
        aw.save()
        return aw