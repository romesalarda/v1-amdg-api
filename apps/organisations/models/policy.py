from django.db import models
from django.contrib.auth import get_user_model


class OrganisationEventPolicy(models.Model):
    '''
    Model representing the event policy for an organisation. Events created under an organisation will adhere to the rules defined in this policy.
    '''
    organisation = models.OneToOneField(
        'organisations.Organisation',
        on_delete=models.CASCADE,
        related_name='event_policy'
    )

    allow_external_events = models.BooleanField(default=False, help_text="Whether events under this organisation can be created by external users.")
    allow_attendee_deletions = models.BooleanField(default=False, help_text="Whether attendees can be deleted from events under this organisation.")
    allow_workshops = models.BooleanField(default=True, help_text="Whether events under this organisation can be workshops.")
    allow_product_releases = models.BooleanField(default=True, help_text="Whether events under this organisation can have product releases.")
    allow_sponsors = models.BooleanField(default=True, help_text="Whether events under this organisation can have sponsors.")

    require_long_description = models.BooleanField(default=False, help_text="Whether events under this organisation must have a long description.")
    require_short_description = models.BooleanField(default=False, help_text="Whether events under this organisation must have a short description.")
    require_landing_image = models.BooleanField(default=False, help_text="Whether events under this organisation must have a landing image.")

    product_release_must_be_approved_by_organisation = models.BooleanField(default=True, help_text="Whether product releases must be approved by the organisation.")
    must_be_approved_by_organisation = models.BooleanField(default=True, help_text="Whether events must be approved by the organisation.")

    max_attendees_per_event = models.PositiveIntegerField(default=100, help_text="The maximum number of attendees allowed for events under this organisation. Set to 0 for unlimited.")
    max_events_per_organiser = models.PositiveIntegerField(default=10, help_text="The maximum number of events an organiser can create under this organisation. Set to 0 for unlimited.")

    card_payments_are_allowed = models.BooleanField(default=True, help_text="Whether card payments are allowed for events under this organisation.")
    bank_transfers_are_allowed = models.BooleanField(default=True, help_text="Whether bank transfers are allowed for events under this organisation.")

    max_package_price = models.DecimalField(max_digits=10, decimal_places=2, default=1000.00, help_text="The maximum price for event packages under this organisation.")


    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_event_policies'
    )

    def __str__(self):
        return f"Global Event Policy for {self.organisation.name}"

class OrganisationEventTypePolicyRestriction(models.Model):
    '''
    Model representing restrictions on event types for an organisation. This allows organisations to specify which event types are allowed or disallowed for events created under them.
    '''
    organisation = models.ForeignKey(
        'organisations.Organisation',
        on_delete=models.CASCADE,
        related_name='event_type_restrictions'
    )
    event_type = models.ForeignKey(
        'events.EventType',
        on_delete=models.CASCADE,
        related_name='organisation_restrictions'
    )
    
    is_allowed = models.BooleanField(default=True, help_text="Whether this event type is allowed for events under this organisation.")
    requires_approval = models.BooleanField(default=False, help_text="Whether events of this type require approval from the organisation.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_event_type_restrictions'
    )

    def __str__(self):
        status = "Allowed" if self.is_allowed else "Disallowed"
        approval = "Requires Approval" if self.requires_approval else "No Approval Needed"
        return f"{status} Event Type '{self.event_type}' for {self.organisation.name} ({approval})"