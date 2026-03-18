from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0024_alter_eventpermission_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventsettings',
            name='requires_verified_sponsors_for_checkout',
            field=models.BooleanField(
                default=False,
                help_text='Whether sponsorship checkout requires verified sponsors before completion.',
            ),
        ),
        migrations.AddField(
            model_name='eventsettings',
            name='requires_invite_acceptance_for_checkout',
            field=models.BooleanField(
                default=False,
                help_text='Whether sponsorship checkout is limited to accepted invite token flow.',
            ),
        ),
        migrations.AddField(
            model_name='eventsettings',
            name='sponsor_checkout_policy_notes',
            field=models.TextField(
                blank=True,
                null=True,
                help_text='Optional organiser notes describing sponsorship checkout policy.',
            ),
        ),
    ]
