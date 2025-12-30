from apps.common.evaluator import BaseEvaluator, BaseContext, rules_apply


class ProductContext(BaseContext): #not in use
    '''
    Context class for payment-related evaluations.
    '''
    pass

class ProductRuleEvaluator(BaseEvaluator): #not in use
    '''
    Evaluator for payment rules.
    '''

def product_rules_apply(rules, context: ProductContext): #not in use
    '''
    @param rules: Iterable of ProductRule instances
    @param context: ProductContext instance
    @return: bool indicating if all rules apply in given context
    '''
    
    evaluator = ProductRuleEvaluator()

    return all(
        evaluator.evaluate(rule, context)
        for rule in rules
    )    