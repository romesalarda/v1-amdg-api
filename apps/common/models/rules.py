from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from django.core.exceptions import ValidationError

from apps.common.evaluator import BaseEventRuleChoices

import uuid

User = get_user_model()

class AccessRule(models.Model): #TODO: migrate to specific rule models later #TODO: admin register
    '''
    Model representing rules that can be applied to events, products, or discounts.
    '''
    rule_id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    rule_type = models.CharField(
        max_length=30,
        choices=BaseEventRuleChoices.choices,
        default=BaseEventRuleChoices.IS_EVENT_STAFF
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    
    # discount = models.ForeignKey(Discount, on_delete=models.CASCADE, related_name='rules')
    value = models.CharField(max_length=255, help_text="Value associated with the rule (e.g. age limit, organisation name, etc.)", blank=True, null=True)
    
    active = models.BooleanField(default=True)
    
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.PositiveIntegerField()
    target = GenericForeignKey('target_type', 'target_id')
    
    def clean(self):
        if self.rule_type in [
            BaseEventRuleChoices.IS_AGE_LT,
            BaseEventRuleChoices.IS_AGE_GT,
            BaseEventRuleChoices.ORGANISATION_MATCHES,
            BaseEventRuleChoices.VALUE_MATCHES,
            BaseEventRuleChoices.EVENT_STAFF_ROLE_MATCHES,
            BaseEventRuleChoices.NAME_MATCHES,
            BaseEventRuleChoices.LOCATION_MATCHES,
            BaseEventRuleChoices.CODE_MATCHES,
        ] and not self.value:
            raise ValidationError(f"Rule type {self.rule_type} requires a value.")
        
        if self.rule_type in [
            BaseEventRuleChoices.IS_AGE_GT, 
            BaseEventRuleChoices.IS_AGE_LT
        ]:
            try:
                int(self.value)
            except (TypeError, ValueError):
                raise ValidationError(f"Rule type {self.rule_type} requires an integer value.")
    
    def __str__(self):
        return self.name
    
    def __repr__(self):
        return f"<AccessRule {self.name} (ID: {self.rule_id})>"
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)