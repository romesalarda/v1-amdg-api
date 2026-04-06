from django.db import models
from djmoney.models.fields import MoneyField
from apps.common.models.verification import RequiresVerificationModel
import uuid

class CreditExpenseTypeChoices(models.TextChoices):
    VENUE_COST = 'VENUE_COST', 'Venue Cost'
    FOOD_COST = 'FOOD_COST', 'Food Cost'
    CLERGY_COST = 'CLERGY_COST', 'Clergy Cost'
    CONSECRATED_RELIGIOUS_COST = 'CONSECRATED_RELIGIOUS_COST', 'Consecrated Religious Cost'
    LOGISTICS_COST = 'LOGISTICS_COST', 'Logistics Cost'
    TRANSPORT_COST = 'TRANSPORT_COST', 'Transport Cost'
    STAFF_COST = 'STAFF_COST', 'Staff Cost'
    CREATIVES_COST = 'CREATIVES_COST', 'Creatives Cost'
    TECHNICAL_COST = 'TECHNICAL_COST', 'Technical Cost'
    STIPEND = 'STIPEND', 'Stipend'
    OTHER = 'OTHER', 'Other'


class CreditExpense(RequiresVerificationModel):
    '''
    Model to represent a credit expense in the payment system. Useful for tracking outgoing event payments 
    e.g. venue costs, food costs, etc. The model includes a unique credit ID, the amount of the expense, a description, and a timestamp for when the expense was created.
    The model inherits from RequiresVerificationModel to ensure that the credit expense can be verified before being
    '''
    credit_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, primary_key=True)
    amount = MoneyField(max_digits=14, decimal_places=2, default_currency='GBP')
    description = models.TextField()
    expense_type = models.CharField(max_length=20, choices=CreditExpenseTypeChoices.choices, default=CreditExpenseTypeChoices.OTHER)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Credit Expense: {self.description} - Amount: {self.amount}"