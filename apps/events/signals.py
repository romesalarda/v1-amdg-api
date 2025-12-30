from django.db.models.signals import post_save, pre_save, pre_delete, post_delete
from django.dispatch import receiver

from apps.events.models.events import Event

@receiver(post_save, sender=Event)
def create_default_event_settings(sender, instance: Event, created: bool, **kwargs):
    '''
    Signal to create default EventSettings when a new Event is created.
    '''
    if created:
        from apps.events.models.events import EventSettings
        EventSettings.objects.create(event=instance)

@receiver(pre_save, sender=Event)
def update_event_settings(sender, instance: Event, **kwargs):
    '''
    Signal to update EventSettings when an Event is updated.
    '''
    try:
        settings = instance.settings
        # Add any specific updates to settings here if needed
        settings.save()
    except Event.settings.RelatedObjectDoesNotExist:
        pass

@receiver(pre_delete, sender=Event)
def delete_event_settings(sender, instance: Event, **kwargs):
    '''
    Signal to delete EventSettings when an Event is deleted.
    '''
    try:
        instance.settings.delete()
    except Event.settings.RelatedObjectDoesNotExist:
        pass