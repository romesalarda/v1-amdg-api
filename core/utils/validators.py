from django.core.validators import BaseValidator, RegexValidator
from django.core.exceptions import ValidationError

class PhoneNumberValidator(RegexValidator):
    """
    Validator for phone numbers. Validates international and local formats.
    """
    regex = r'^\+?1?\d{9,15}$'
    message = (
        "Enter a valid phone number. Up to 15 digits allowed. "
        "It may start with a '+' sign followed by country code."
    )
    flags = 0

    def __init__(self, *args, **kwargs):
        super().__init__(regex=self.regex, message=self.message, flags=self.flags, *args, **kwargs)