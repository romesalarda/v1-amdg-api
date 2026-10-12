"""Periodic safety net for payment fulfilment."""
from celery import shared_task

from apps.payments.services.completion import fulfil_outstanding_payments


@shared_task(name='payments.fulfil_outstanding_payments')
def fulfil_outstanding_payments_task(min_age_minutes: int = 5, batch_size: int = 100):
    """Retry COMPLETED payments whose post-completion processing never ran."""
    return fulfil_outstanding_payments(min_age_minutes=min_age_minutes, batch_size=batch_size)
