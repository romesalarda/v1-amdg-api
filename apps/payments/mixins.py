from django.db import models
from djmoney.models.fields import MoneyField
from django.core.exceptions import ValidationError

class PayableModel(models.Model):
    '''
    Mixin to indicate that a model supports payments.
    '''
    amount = MoneyField(max_digits=14, decimal_places=2, default_currency='GBP')
    
    class Meta:
        abstract = True
        
    def clean(self):
        super().clean()
        if self.amount.amount < 0:
            raise ValidationError({'amount': 'Amount must be non-negative.'})
        
    @property
    def currency(self):
        return self.amount.currency.code

    def is_zero_amount(self):
        return self.amount.amount == 0

    def is_positive(self):
        return self.amount.amount > 0