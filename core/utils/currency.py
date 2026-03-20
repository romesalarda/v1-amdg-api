
def format_price(amount, currency):

    general_mapping = {
        "GBP": "£",
        "USD": "$",
        "EUR": "€",
    }

    if amount is None or currency is None:
        return "Free"
    return f"{general_mapping.get(currency, currency)}{amount}"
