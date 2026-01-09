from django.core.validators import BaseValidator, RegexValidator
from django.core.exceptions import ValidationError

class PhoneNumberValidator(RegexValidator):
    """
    Validator for phone numbers. Validates international and local formats.
    Allows spaces, dashes, parentheses for formatting.
    """
    regex = r'^[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,5}[-\s\.]?[0-9]{1,6}$'
    message = (
        "Enter a valid phone number. Accepts international format with spaces, "
        "dashes, or parentheses (e.g., +44 1234 567890, (555) 123-4567)."
    )
    flags = 0

    def __init__(self, *args, **kwargs):
        super().__init__(regex=self.regex, message=self.message, flags=self.flags, *args, **kwargs)