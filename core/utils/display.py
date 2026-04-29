import uuid

def generate_human_readable_id(max_length, prefix, *args, separator='-'):
    """
    Generates a unique identifier with the given prefix and maximum length.
    Ensures the total length does not exceed max_length.
    """
    # prefix, *args separated by hyphens then a unique part to fill max_length
    base = separator.join([prefix] + [str(arg) for arg in args if arg])
    if len(base) >= max_length:
        raise ValueError("Base length exceeds maximum length.")
    
    unique_part_length = max_length - len(base) - 1  # -1 for hyphen
    unique_part = str(uuid.uuid4()).replace('-', '')[:unique_part_length].upper()
    return f"{base}-{unique_part}"

def generate_alphanumeric_id(length):
    """
    Generates a random alphanumeric identifier of the specified length.
    """
    import random
    import string

    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choices(characters, k=length))

def try_generate_unique_code(model_class, length, max_attempts=5, lookup_field='code'):
    """
    Tries to generate a unique alphanumeric code for the given model class.
    Retries up to max_attempts times to avoid collisions.
    """
    attempts = 0
    while attempts < max_attempts:
        code = generate_alphanumeric_id(length)
        if not model_class.objects.filter(**{lookup_field: code}).exists():
            return code
        attempts += 1
    raise ValueError("Could not generate a unique code after multiple attempts.")

def try_generate_unique_display_code(model_class, length, prefix, args, lookup_field='display_code', max_attempts=5):
    """
    Tries to generate a unique human-readable display code for the given model class.
    Retries up to max_attempts times to avoid collisions.
    """
    attempts = 0
    while attempts < max_attempts:
        code = generate_human_readable_id(length, prefix, *args)
        if not model_class.objects.filter(**{lookup_field: code}).exists():
            return code
        attempts += 1
    raise ValueError("Could not generate a unique display code after multiple attempts.")