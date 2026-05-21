"""
AttendeeCheckIn model — granular audit log for every check-in event.

EventAttendance tracks current state; AttendeeCheckIn is the immutable audit trail.
"""
from django.db import models
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


class CheckInAction(models.TextChoices):
    CHECK_IN = 'CHECK_IN', 'Check In'
    CHECK_OUT = 'CHECK_OUT', 'Check Out'


class CheckInMethod(models.TextChoices):
    QR_CODE = 'QR_CODE', 'QR Code'
    MANUAL = 'MANUAL', 'Manual'
    ADMIN = 'ADMIN', 'Admin'


class CheckInScanResult(models.TextChoices):
    SUCCESS = 'SUCCESS', 'Success'
    ALREADY_CHECKED_IN = 'ALREADY_CHECKED_IN', 'Already Checked In'
    ALREADY_CHECKED_OUT = 'ALREADY_CHECKED_OUT', 'Already Checked Out'
    INVALID_TICKET = 'INVALID_TICKET', 'Invalid Ticket'
    CANCELLED_ATTENDEE = 'CANCELLED_ATTENDEE', 'Cancelled Attendee'
    CANCELLED_TICKET = 'CANCELLED_TICKET', 'Cancelled Ticket'
    NOT_FOUND = 'NOT_FOUND', 'Not Found'
    OUTSTANDING_PAYMENTS = 'OUTSTANDING_PAYMENTS', 'Outstanding Payments'
    ERROR = 'ERROR', 'Error'


class AttendeeCheckIn(models.Model):
    """
    Immutable audit record for each check-in/check-out attempt.

    Created on every scan (success or failure). EventAttendance holds
    the current state; this model holds the full history.
    """
    check_in_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Core relationships
    attendee = models.ForeignKey(
        'attendee.Attendee',
        on_delete=models.CASCADE,
        related_name='check_in_records',
    )
    ticket = models.ForeignKey(
        'bookings.Ticket',
        on_delete=models.SET_NULL,
        related_name='check_in_records',
        null=True,
        blank=True,
    )
    alternative_signin = models.ForeignKey(
        'bookings.AttendeeAlternativeSigninIdentifier',
        on_delete=models.SET_NULL,
        related_name='check_in_records',
        null=True,
        blank=True,
    )

    # Action & result
    action = models.CharField(
        max_length=20,
        choices=CheckInAction.choices,
        default=CheckInAction.CHECK_IN,
    )
    method = models.CharField(
        max_length=20,
        choices=CheckInMethod.choices,
        default=CheckInMethod.MANUAL,
    )
    scan_result = models.CharField(
        max_length=30,
        choices=CheckInScanResult.choices,
        default=CheckInScanResult.SUCCESS,
    )

    # Venue
    venue = models.ForeignKey(
        'events.EventVenue',
        on_delete=models.SET_NULL,
        related_name='check_in_records',
        null=True,
        blank=True,
    )
    venue_room = models.ForeignKey(
        'events.EventVenueRoom',
        on_delete=models.SET_NULL,
        related_name='check_in_records',
        null=True,
        blank=True,
    )

    # Who & when
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='performed_check_ins',
        null=True,
        blank=True,
    )
    performed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Snapshot fields (denormalised for fast broadcast / offline log replay)
    attendee_status_snapshot = models.CharField(max_length=30, blank=True)
    has_outstanding_payments = models.BooleanField(default=False)

    # Optional metadata
    notes = models.TextField(blank=True)
    device_info = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = 'Attendee Check-In'
        verbose_name_plural = 'Attendee Check-Ins'
        ordering = ['-performed_at']
        indexes = [
            models.Index(fields=['attendee', 'performed_at']),
            models.Index(fields=['performed_at']),
        ]

    def __str__(self):
        return (
            f"{self.action} — {self.attendee} via {self.method} "
            f"({self.scan_result}) at {self.performed_at}"
        )

    def __repr__(self):
        return (
            f"<AttendeeCheckIn {self.check_in_id}: "
            f"{self.action} {self.scan_result}>"
        )
