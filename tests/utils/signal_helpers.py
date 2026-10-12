"""
Payment fulfilment test utilities.

Post-completion processing is explicit (``apps.payments.services.completion``),
not signal-driven, so saving a COMPLETED payment in a test has no side effects.

To exercise the processing::

    from tests.utils.signal_helpers import fulfil_payment_now

    fulfil_payment_now(payment)

or, to test the real ``on_commit`` scheduling::

    with self.captureOnCommitCallbacks(execute=True):
        complete_payment(payment)
"""
from apps.payments.services.completion import fulfil_payment


def fulfil_payment_now(payment) -> bool:
    """Run fulfilment synchronously (no ``on_commit`` deferral needed)."""
    return fulfil_payment(payment.pk)
