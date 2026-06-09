from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

import uuid


class WorkshopInterestSubmission(models.Model):
    '''
    Represents an attendee's ranked interest in workshops for a given event.

    One submission per (attendee × event). The attendee ranks each workshop they
    are interested in via related WorkshopInterestRank entries.

    Once is_finalised is True the submission is locked for allocation processing.
    '''

    submission_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="workshop_interest_submissions",
    )
    attendee = models.ForeignKey(
        "attendee.Attendee",
        on_delete=models.CASCADE,
        related_name="workshop_interest_submissions",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_finalised = models.BooleanField(
        default=False,
        help_text=_("When True the submission is locked and ready for allocation."),
    )

    class Meta:
        verbose_name = _("Workshop Interest Submission")
        verbose_name_plural = _("Workshop Interest Submissions")
        unique_together = ('event', 'attendee')

    def __str__(self):
        return f"{self.attendee} — {self.event} interest submission"

    def clean(self):
        if self.attendee_id and self.event_id:
            if str(self.attendee.event_id) != str(self.event_id):
                raise ValidationError(_("Attendee must belong to the same event as this submission."))


class WorkshopInterestRank(models.Model):
    '''
    A single ranked entry within a WorkshopInterestSubmission.

    rank=1 is the attendee's most preferred workshop.
    rank values must be unique within a submission (no two entries share the same rank).
    Each workshop may only appear once per submission.
    '''

    submission = models.ForeignKey(
        WorkshopInterestSubmission,
        on_delete=models.CASCADE,
        related_name="ranks",
    )
    workshop = models.ForeignKey(
        "workshops.Workshop",
        on_delete=models.CASCADE,
        related_name="interest_ranks",
    )
    rank = models.PositiveIntegerField(
        help_text=_("Preference rank for this workshop (1 = most preferred)."),
    )

    class Meta:
        verbose_name = _("Workshop Interest Rank")
        verbose_name_plural = _("Workshop Interest Ranks")
        unique_together = [
            ('submission', 'workshop'),
            ('submission', 'rank'),
        ]
        ordering = ['rank']

    def __str__(self):
        return f"Rank {self.rank}: {self.workshop} (submission {self.submission_id})"

    def clean(self):
        if self.workshop_id and self.submission_id:
            submission = self.submission
            if str(self.workshop.event_id) != str(submission.event_id):
                raise ValidationError(_("Workshop must belong to the same event as the interest submission."))
        if self.rank is not None and self.rank < 1:
            raise ValidationError(_("Rank must be a positive integer (1 or greater)."))
