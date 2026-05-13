
from django.db import models
from django.conf import settings

from apps.common.models.verification import RequiresVerificationModel
from moneyed import Money
from django.core.validators import MinLengthValidator, MaxLengthValidator
import uuid


class BudgetProposal(RequiresVerificationModel):
    '''
    Budget proposals are created by event organizers to propose a budget for an event.
    They can be verified by admins or finance team members before being approved.

    total_credits and total_debits are computed on-demand via properties to avoid
    stale M2M aggregation issues in save().
    '''
    proposal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    
    proposal_title = models.CharField(max_length=255)
    proposal_description = models.TextField(
        validators=[
            MinLengthValidator(10),
            MaxLengthValidator(2000),
        ]
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='budget_proposals',
        null=True,
        blank=True,
    ) 
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='budget_proposals_made',
        null=True,
        blank=True,
    )

    credit_expenses = models.ManyToManyField(
        'payments.CreditExpense',
        related_name='budget_proposals',
        blank=True,
    )

    debit_expenses = models.ManyToManyField(
        'payments.DebitExpense',
        related_name='budget_proposals',
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Budget Proposal'
        verbose_name_plural = 'Budget Proposals'
        indexes = [
            models.Index(fields=['event', 'created_at']),
            models.Index(fields=['verification_status']),
        ]

    def __str__(self):
        return f"Budget Proposal: {self.proposal_title} for Event: {self.event.title if self.event else 'N/A'}"

    @property
    def total_credits(self):
        """Sum of all linked credit expense amounts."""
        credits = list(self.credit_expenses.all())
        if not credits:
            return Money(0, 'GBP')
        total = credits[0].amount
        for credit in credits[1:]:
            if credit.amount.currency == total.currency:
                total += credit.amount
        return total

    @property
    def total_debits(self):
        """Sum of all linked debit expense amounts (estimated inbound)."""
        debits = list(self.debit_expenses.all())
        if not debits:
            return Money(0, 'GBP')
        total = debits[0].amount
        for debit in debits[1:]:
            if debit.amount.currency == total.currency:
                total += debit.amount
        return total

    def clean(self):
        super().clean()