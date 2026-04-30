# Generated migration — deduplicates existing EventNotification rows then adds
# a unique constraint to prevent future duplicates for the same
# payment+order combination.

from django.db import migrations, models


def deduplicate_notifications(apps, schema_editor):
    """
    For each (notification_type, related_payment_id, related_order_id) group
    that has more than one row, keep the earliest record (lowest pk) and delete
    the rest. Only rows where both FKs are non-null are affected, matching the
    partial unique constraint that follows.
    """
    EventNotification = apps.get_model('events', 'EventNotification')

    # Fetch all groups that have duplicates.
    seen = {}
    to_delete = []

    qs = (
        EventNotification.objects
        .filter(related_payment__isnull=False, related_order__isnull=False)
        .order_by('id')
        .values_list('id', 'notification_type', 'related_payment_id', 'related_order_id')
    )

    for pk, ntype, payment_id, order_id in qs:
        key = (ntype, payment_id, order_id)
        if key in seen:
            to_delete.append(pk)
        else:
            seen[key] = pk

    if to_delete:
        EventNotification.objects.filter(pk__in=to_delete).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0028_event_external_event_event_external_link_and_more'),
    ]

    operations = [
        # Step 1: remove duplicate rows before the unique index is built.
        migrations.RunPython(
            deduplicate_notifications,
            reverse_code=migrations.RunPython.noop,
        ),
        # Step 2: add the partial unique constraint.
        migrations.AddConstraint(
            model_name='eventnotification',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    related_payment__isnull=False,
                    related_order__isnull=False,
                ),
                fields=['notification_type', 'related_payment', 'related_order'],
                name='unique_notification_per_payment_order',
            ),
        ),
    ]
