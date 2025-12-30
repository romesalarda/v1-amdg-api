from django.db import models
from django.utils.translation import gettext_lazy as _
from dataclasses import dataclass
from apps.users.models import CommunityUser

@dataclass
class BaseContext:
    user : CommunityUser | None
    event: object | None
    metadata: dict

class BaseEventRuleChoices(models.TextChoices):

    IS_EVENT_STAFF = 'IS_EVENT_STAFF', _('Is Event Staff') # for staff discounts
    IS_AGE_LT = 'IS_AGE_LT', _('Is Age Less Than') # for age based discounts
    IS_AGE_GT = 'IS_AGE_GT', _('Is Age Greater Than') # for age based discounts
    ORGANISATION_MATCHES = 'ORGANISATION_MATCHES', _('Organisation Matches') # for organisation based discounts
    VALUE_MATCHES = 'VALUE_MATCHES', _('Value Matches') # for discount codes etc.
    EVENT_STAFF_ROLE_MATCHES = 'EVENT_STAFF_ROLE_MATCHES', _('Event Staff Role Matches') # for specific staff role discounts
    NAME_MATCHES = 'NAME_MATCHES', _('Name Matches') # for name based discounts
    LOCATION_MATCHES = 'LOCATION_MATCHES', _('Location Matches') # for location based discounts
    CODE_MATCHES = 'CODE_MATCHES', _('Code Matches') # for code based discounts

class BaseEvaluator:

    def evaluate(self, rule, context) -> bool:
        '''
        Docstring for evaluate
        
        :param self: BaseEvaluator instance
        :param rule: an objet that supports rules instance
        :param context: BaseContext instance
        :return: bool indicating if the rule applies in given context
        :rtype: bool
        '''
        if not getattr(rule, 'rule_type', None):
            raise ValueError(f"rule model class '{rule.__class__.__name__}' must have a 'rule_type' attribute")
        
        handler = self.get_handler(rule.rule_type)
        return handler(rule, context)

    def get_handler(self, rule_type):
        '''
        Gets the appropriate handler function for the given rule type.
        
        :param self: BaseEvaluator instance
        :param rule_type: string representing the type of rule
        :return: function that handles the evaluation of the given rule type
        '''
        return {
            BaseEventRuleChoices.IS_EVENT_STAFF: self.is_event_staff,
            BaseEventRuleChoices.IS_AGE_LT: self.is_age_lt,
            BaseEventRuleChoices.IS_AGE_GT: self.is_age_gt,
            BaseEventRuleChoices.ORGANISATION_MATCHES: self.organisation_matches,
            BaseEventRuleChoices.VALUE_MATCHES: self.value_matches,
            BaseEventRuleChoices.EVENT_STAFF_ROLE_MATCHES: self.staff_role_matches,
            BaseEventRuleChoices.NAME_MATCHES: self.name_matches,
            BaseEventRuleChoices.LOCATION_MATCHES: self.location_matches,
            BaseEventRuleChoices.CODE_MATCHES: self.code_matches,
        }[rule_type]

    def is_event_staff(self, rule, context):
        return context.user and context.metadata.get("is_event_staff", False)

    def is_age_lt(self, rule, context):
        return context.metadata.get("age", None) is not None and context.metadata.get("age") < int(rule.value)
    
    def is_age_gt(self, rule, context):
        return context.metadata.get("age", None) is not None and context.metadata.get("age") > int(rule.value)

    def value_matches(self, rule, context):
        return context.metadata.get("code") == rule.value
    
    def organisation_matches(self, rule, context):
        return rule.value in context.metadata.get("organisations", [])
    
    def staff_role_matches(self, rule, context):
        return context.metadata.get("staff_roles") and rule.value in context.metadata.get("staff_roles", [])
        
    def name_matches(self, rule, context):
        return rule.value.strip().lower() in context.metadata.get("full_name", "").strip().lower()
    
    def location_matches(self, rule, context):
        return context.metadata.get("location").lower() == rule.value.lower()
    
    def code_matches(self, rule, context):
        return context.metadata.get("code") == rule.value

def rules_apply(rules, context, evaluator: BaseEvaluator = None):
    '''
    @param rules: Iterable of DiscountRule instances
    @param context: DiscountContext instance
    @return: bool indicating if all rules apply in given context
    '''

    return all(
        evaluator.evaluate(rule, context)
        for rule in rules
    )