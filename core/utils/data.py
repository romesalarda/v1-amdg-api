from django.db import IntegrityError, transaction

def save_with_unique_field(
    instance,
    field_name,
    generator,
    max_attempts=5,
    save_kwargs=None,
):
    save_kwargs = save_kwargs or {}

    if getattr(instance, field_name):
        return instance.save(**save_kwargs)

    for _ in range(max_attempts):
        setattr(instance, field_name, generator())
        try:
            with transaction.atomic():
                return instance.save(**save_kwargs)
        except IntegrityError:
            continue

    raise RuntimeError(f"Unable to generate unique value for {field_name}")
