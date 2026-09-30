"""
Event policy services.

Encapsulates the cross-app logic between an event's own `EventPolicy` and its
organisation's `OrganisationEventPolicy` baseline, keeping the models free of
that coupling.
"""
from apps.events.models import EventPolicy, Event
from apps.organisations.models import OrganisationEventPolicy
from typing import Tuple


def get_or_create_event_policy(event: Event) -> Tuple[EventPolicy, bool]:
    """
    Get or create the `EventPolicy` for an event, seeded from the organisation baseline.

    Args:
        event (Event): The event for which to get or create the policy.

    Returns:
        Tuple[EventPolicy, bool]: The `EventPolicy` instance and a boolean indicating whether it was created.
    """

    defaults = {}
    if event.organisation_id:
        baseline, _ = OrganisationEventPolicy.objects.get_or_create(
            organisation=event.organisation,
        )
        defaults = {
            field: getattr(baseline, field)
            for field in EventPolicy.POLICY_FIELDS
        }
    return EventPolicy.objects.get_or_create(event=event, defaults=defaults)


def get_effective_policy_values(event_policy: EventPolicy) -> dict:
    """
    Combine an event's policy values with its organisation's current ceiling.

    Args:
        event_policy (EventPolicy): The event policy to evaluate.

    Returns:
        dict: A dictionary of effective policy values.
    """

    values = {field: getattr(event_policy, field) for field in EventPolicy.POLICY_FIELDS}
    organisation = event_policy.event.organisation
    if organisation is None:
        return values

    try:
        baseline = organisation.event_policy
    except OrganisationEventPolicy.DoesNotExist:
        return values

    for field in EventPolicy.ALLOW_FIELDS:
        values[field] = values[field] and getattr(baseline, field)
    for field in EventPolicy.REQUIRE_FIELDS:
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
