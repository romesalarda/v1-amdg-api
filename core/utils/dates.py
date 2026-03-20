
def valid_date_of_birth(date_of_birth, raise_exception=True):
    '''
    Validate that the provided date_of_birth is not in the future
    and is a reasonable date (e.g., not before 1900-01-01).
    '''
    from datetime import date
    if not date_of_birth:
        return False
    
    if date_of_birth > date.today():
        if raise_exception:
            raise ValueError("Date of birth cannot be in the future.")
        return False
    if date_of_birth < date(1900, 1, 1):
        if raise_exception:
            raise ValueError("Date of birth is unrealistically old.")
        return False
    return True

def parse_date(date_str):
    '''
    Parse a date string in ISO format (YYYY-MM-DD) and return a date object.
    '''
    from datetime import datetime
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Invalid date format. Expected YYYY-MM-DD.")