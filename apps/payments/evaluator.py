from dataclasses import dataclass
from typing import Any

from apps.payments.models import DiscountRule, DiscountRuleTypeChoices

from apps.users.models import CommunityUser

@dataclass
class DiscountContext:
    user : CommunityUser | None
    event: object | None
    metadata: dict


class DiscountRuleEvaluator:

    def evaluate(self, rule: DiscountRule, context: DiscountContext) -> bool:

        if not isinstance(rule, DiscountRule):
            raise ValueError("rule must be an instance of DiscountRule")
        
        if not isinstance(context, DiscountContext):
            raise ValueError(
                "context must be an instance of DiscountContext. " + 
                "Expected Dataclass DiscountContext with user, event, metadata fields."
                )

        handler = self.get_handler(rule.rule_type)
        return handler(rule, context)

    def get_handler(self, rule_type):
        return {
            DiscountRuleTypeChoices.IS_EVENT_STAFF: self.is_event_staff,
            DiscountRuleTypeChoices.IS_AGE_LT: self.is_age_lt,
            DiscountRuleTypeChoices.IS_AGE_GT: self.is_age_gt,
            DiscountRuleTypeChoices.ORGANISATION_MATCHES: self.organisation_matches,
            DiscountRuleTypeChoices.VALUE_MATCHES: self.value_matches,
            DiscountRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES: self.staff_role_matches,
            DiscountRuleTypeChoices.NAME_MATCHES: self.name_matches,
            DiscountRuleTypeChoices.LOCATION_MATCHES: self.location_matches,
            DiscountRuleTypeChoices.CODE_MATCHES: self.code_matches,
        }[rule_type]

    def is_event_staff(self, rule, context):
        return context.user and context.metadata.get("is_event_staff", True) # changed to true 

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
        location = context.metadata.get("location")
        if location is None:
            return False
        return location.lower() == rule.value.lower()
    
    def code_matches(self, rule, context):
        code = context.metadata.get("code")
        # Guard: None must never match a real rule value
        if code is None:
            return False
        return code == rule.value

def discount_applies(discount, context):
    '''
    @param discount: Discount instance
    @param context: DiscountContext instance
    @return: bool indicating if discount applies in given context
    '''
    evaluator = DiscountRuleEvaluator()
    rules = discount.rules.filter(active=True)
    return all(
        evaluator.evaluate(rule, context)
        for rule in rules
    )