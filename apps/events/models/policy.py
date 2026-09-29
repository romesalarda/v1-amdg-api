from django.db import models


class EventPolicy(models.Model):
    """Event-specific policy values initialized from its organisation policy."""

    event = models.OneToOneField(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='policy',
    )

    allow_external_events = models.BooleanField(default=False)
    allow_attendee_deletions = models.BooleanField(default=False)
    allow_workshops = models.BooleanField(default=True)
    allow_product_releases = models.BooleanField(default=True)
    allow_sponsors = models.BooleanField(default=True)

    require_long_description = models.BooleanField(default=False)
    require_short_description = models.BooleanField(default=False)
    require_landing_image = models.BooleanField(default=False)

    product_release_must_be_approved_by_organisation = models.BooleanField(default=True)
    must_be_approved_by_organisation = models.BooleanField(default=True)

    max_attendees_per_event = models.PositiveIntegerField(default=100)
    card_payments_are_allowed = models.BooleanField(default=True)
    bank_transfers_are_allowed = models.BooleanField(default=True)
    max_package_price = models.DecimalField(max_digits=10, decimal_places=2, default=1000.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    ALLOW_FIELDS = (
        'allow_external_events',
        'allow_attendee_deletions',
        'allow_workshops',
        'allow_product_releases',
        'allow_sponsors',
        'card_payments_are_allowed',
        'bank_transfers_are_allowed',
    )
    REQUIRE_FIELDS = (
        'require_long_description',
        'require_short_description',
        'require_landing_image',
        'product_release_must_be_approved_by_organisation',
        'must_be_approved_by_organisation',
    )
    POLICY_FIELDS = ALLOW_FIELDS + REQUIRE_FIELDS + (
        'max_attendees_per_event',
        'max_package_price',
    )

    @classmethod
    def get_or_create_for_event(cls, event):
        defaults = {}
        if event.organisation_id:
            from apps.organisations.models import OrganisationEventPolicy

            baseline, _ = OrganisationEventPolicy.objects.get_or_create(
                organisation=event.organisation,
            )
            defaults = {
                field: getattr(baseline, field)
                for field in cls.POLICY_FIELDS
            }
        return cls.objects.get_or_create(event=event, defaults=defaults)

    def __str__(self):
        return f"Policy for {self.event.title}"

    def get_effective_values(self):
        """Combine this event's values with its organisation's current ceiling."""
        values = {field: getattr(self, field) for field in self.POLICY_FIELDS}
        organisation = self.event.organisation
        if organisation is None:
            return values

        from apps.organisations.models import OrganisationEventPolicy

        try:
            baseline = organisation.event_policy
        except OrganisationEventPolicy.DoesNotExist:
            return values

        for field in self.ALLOW_FIELDS:
            values[field] = values[field] and getattr(baseline, field)
        for field in self.REQUIRE_FIELDS:
            values[field] = values[field] or getattr(baseline, field)

        event_limit = values['max_attendees_per_event']
        organisation_limit = baseline.max_attendees_per_event
        if event_limit == 0:
            values['max_attendees_per_event'] = organisation_limit
        elif organisation_limit != 0:
            values['max_attendees_per_event'] = min(event_limit, organisation_limit)

        values['max_package_price'] = min(
            values['max_package_price'],
            baseline.max_package_price,
        )
        return values
