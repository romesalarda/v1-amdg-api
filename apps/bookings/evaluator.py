from dataclasses import dataclass

from apps.users.models import CommunityUser
from apps.bookings.models.booking import BookingPackage, PackageRuleTypeChoices

@dataclass
class PaymentPackageContext:
    user : CommunityUser | None
    event: object | None
    metadata: dict


class PaymentPackageContextBuilder:

    def evaluate(self, rule: BookingPackage, context: PaymentPackageContext) -> bool:
        handler = self.get_handler(rule.rule_type)
        return handler(rule, context)

    def get_handler(self, rule_type):
        return {
            PackageRuleTypeChoices.IS_EVENT_STAFF: self.is_event_staff,
            PackageRuleTypeChoices.IS_AGE_LT: self.is_age_lt,
            PackageRuleTypeChoices.IS_AGE_GT: self.is_age_gt,
            PackageRuleTypeChoices.ORGANISATION_MATCHES: self.organisation_matches,
            PackageRuleTypeChoices.VALUE_MATCHES: self.value_matches,
            PackageRuleTypeChoices.EVENT_STAFF_ROLE_MATCHES: self.staff_role_matches,
            PackageRuleTypeChoices.NAME_MATCHES: self.name_matches,
            PackageRuleTypeChoices.LOCATION_MATCHES: self.location_matches,
        }[rule_type]

    def is_event_staff(self, rule, context):
        return context.user and context.metadata.get("is_event_staff", False)

    def is_age_lt(self, rule, context):
        return context.user and context.metadata.get("age", None) is not None and context.metadata.get("age") < int(rule.value)
    
    def is_age_gt(self, rule, context):
        return context.user and context.metadata.get("age", None) is not None and context.metadata.get("age") > int(rule.value)

    def value_matches(self, rule, context):
        return context.metadata.get("code") == rule.value
    
    def organisation_matches(self, rule, context):
        return str(rule.value) in context.metadata.get("organisations", [])
    
    def staff_role_matches(self, rule, context):
        return context.metadata.get("staff_roles") and rule.value in context.metadata.get("staff_roles", [])
        
    def name_matches(self, rule, context):
        return context.user and rule.value.strip().lower() in context.metadata.get("full_name", "").strip().lower()
    
    def location_matches(self, rule, context):
        return context.metadata.get("location").lower() == rule.value.lower()

def payment_package_applies(discount, context):
    '''
    @param discount: Discount instance
    @param context: PaymentPackageContext instance
    @return: bool indicating if discount applies in given context
    '''
    evaluator = PaymentPackageContextBuilder()
    rules = discount.rules.filter(active=True)

    return all(
        evaluator.evaluate(rule, context)
        for rule in rules
    )