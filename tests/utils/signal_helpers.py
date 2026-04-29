"""
Signal test utilities.

Provides helpers for isolating tests from payment signal side-effects.

Usage
-----
From a TestCase::

    from tests.utils.signal_helpers import silence_payment_signals

    class MyPaymentTest(TestCase):
        def test_something_unrelated(self):
            with silence_payment_signals():
                payment.save()  # signal will NOT fire

To test the processor logic directly without signal machinery::

    from apps.payments.signals import _process_completed_payment

    class MyProcessorTest(TransactionTestCase):
        # Use TransactionTestCase so transaction.on_commit fires.
        def test_booking_processor(self):
            _process_completed_payment(payment.pk)

Note on TransactionTestCase
---------------------------
Tests that need ``transaction.on_commit`` callbacks to fire must inherit from
``django.test.TransactionTestCase``, not ``django.test.TestCase``.
``TestCase`` wraps each test in a transaction that is never committed, so
``on_commit`` callbacks are never invoked.

If you only need to assert on service-layer behaviour (ticket creation, order
transitions, notification creation), call ``_process_completed_payment``
directly inside a ``TestCase`` — no ``on_commit`` deferral occurs when calling
the function directly.
"""
from contextlib import contextmanager

from django.db.models.signals import post_save


@contextmanager
def silence_payment_signals():
    """
    Context manager that temporarily disconnects the payment completion signal.

    Use in tests that save Payment objects for reasons unrelated to
    post-payment processing, to prevent spurious ticket creation, order
    transitions, or notification creation.
    """
    from apps.payments.signals import handle_payment_completion
    from apps.payments.models import Payment

    post_save.disconnect(handle_payment_completion, sender=Payment)
    try:
        yield
    finally:
        post_save.connect(handle_payment_completion, sender=Payment)
