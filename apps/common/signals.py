from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from apps.common.models.resource import Resource

@receiver(post_delete)
def delete_related_resources(sender, instance, **kwargs):
    
    if sender == Resource:
        return  # Avoid recursion
    # Delete Resource instances related to the deleted instance
    content_type = ContentType.objects.get_for_model(sender)
    Resource.objects.filter( # delete only unprotected resources
        target_type=content_type,
        target_id=instance.pk,
        protected=False
    ).delete()