"""
Workshop allocation service.

All public functions raise ValueError on business-rule violations and
django.core.exceptions.ValidationError on model-level issues.
They perform no HTTP operations and can be used from viewsets, management
commands, or tests alike.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from django.db import transaction

from apps.workshops.models.registration import WorkshopRegistration, WorkshopRegistrationStatus
from apps.workshops.models.workshop import AllocationMode

if TYPE_CHECKING:
    from apps.workshops.models.workshop import Workshop
    from apps.workshops.models.interest import WorkshopInterestSubmission
    from apps.attendee.models.attendee import Attendee
    from django.contrib.auth.models import AbstractBaseUser


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _create_or_update_registration(
    workshop: "Workshop",
    attendee: "Attendee",
    status: str,
    allocation_method: str,
    allocated_by: "AbstractBaseUser | None" = None,
    notes: str | None = None,
) -> WorkshopRegistration:
    """
    Get-or-create a WorkshopRegistration, updating status/method when it already exists.
    """
    registration, _ = WorkshopRegistration.objects.get_or_create(
        workshop=workshop,
        attendee=attendee,
        defaults={
            'status': status,
            'allocation_method': allocation_method,
            'allocated_by': allocated_by,
            'notes': notes,
        },
    )
    if registration.status != status:
        registration.status = status
        registration.allocation_method = allocation_method
        registration.allocated_by = allocated_by
        if notes:
            registration.notes = notes
        registration.save(update_fields=['status', 'allocation_method', 'allocated_by', 'notes'])
    return registration


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

@transaction.atomic
def register_fcfs(
    workshop: "Workshop",
    attendee: "Attendee",
    allocated_by: "AbstractBaseUser | None" = None,
) -> WorkshopRegistration:
    """
    Register an attendee using First Come First Served allocation.

    If the workshop is at capacity the registration is created as WAITLISTED.
    Raises ValueError if the workshop is not in OPEN status.
    """
    from apps.workshops.models.workshop import WorkshopStatus
    if workshop.status != WorkshopStatus.OPEN:
        raise ValueError(f"Workshop '{workshop.title}' is not open for registrations.")

    status = (
        WorkshopRegistrationStatus.WAITLISTED
        if workshop.is_full
        else WorkshopRegistrationStatus.CONFIRMED
    )
    return _create_or_update_registration(
        workshop=workshop,
        attendee=attendee,
        status=status,
        allocation_method=AllocationMode.FCFS,
        allocated_by=allocated_by,
    )


@transaction.atomic
def manual_allocate(
    workshop: "Workshop",
    attendee: "Attendee",
    allocated_by: "AbstractBaseUser",
    notes: str | None = None,
) -> WorkshopRegistration:
    """
    Manually confirm an attendee's registration for a workshop.

    Staff can use this at any time regardless of capacity or workshop status.
    Creates the registration if it does not exist yet.
    """
    return _create_or_update_registration(
        workshop=workshop,
        attendee=attendee,
        status=WorkshopRegistrationStatus.CONFIRMED,
        allocation_method=AllocationMode.MANUAL,
        allocated_by=allocated_by,
        notes=notes,
    )


@transaction.atomic
def cancel_registration(
    registration: WorkshopRegistration,
    cancelled_by: "AbstractBaseUser | None" = None,
) -> WorkshopRegistration:
    """
    Cancel a workshop registration and promote the next person from the waitlist.

    Raises ValueError if the registration is already cancelled.
    """
    if registration.status == WorkshopRegistrationStatus.CANCELLED:
        raise ValueError("Registration is already cancelled.")

    registration.status = WorkshopRegistrationStatus.CANCELLED
    registration.allocated_by = cancelled_by
    registration.save(update_fields=['status', 'allocated_by'])

    # Promote the next waitlisted attendee
    promote_from_waitlist(registration.workshop)
    return registration


def promote_from_waitlist(workshop: "Workshop") -> WorkshopRegistration | None:
    """
    Promote the earliest WAITLISTED registration to CONFIRMED if capacity allows.

    Returns the promoted registration, or None if no promotion occurred.
    """
    if workshop.is_full:
        return None

    next_waiting = (
        workshop.registrations
        .filter(status=WorkshopRegistrationStatus.WAITLISTED)
        .order_by('registered_at')
        .first()
    )
    if next_waiting is None:
        return None

    next_waiting.status = WorkshopRegistrationStatus.CONFIRMED
    next_waiting.allocation_method = AllocationMode.FCFS
    next_waiting.save(update_fields=['status', 'allocation_method'])
    return next_waiting


@transaction.atomic
def run_random_allocation(
    workshop: "Workshop",
    allocated_by: "AbstractBaseUser | None" = None,
) -> dict:
    """
    Randomly allocate attendees from PENDING_ALLOCATION registrations for a workshop.

    Attendees already CONFIRMED or WAITLISTED are unaffected.
    Returns a summary dict with keys 'confirmed', 'waitlisted'.
    """
    pending = list(
        workshop.registrations
        .filter(status=WorkshopRegistrationStatus.PENDING_ALLOCATION)
        .select_for_update()
    )
    random.shuffle(pending)

    confirmed_count = 0
    waitlisted_count = 0
    current_confirmed = workshop.current_registration_count

    for reg in pending:
        if workshop.capacity is None or current_confirmed < workshop.capacity:
            reg.status = WorkshopRegistrationStatus.CONFIRMED
            reg.allocation_method = AllocationMode.RANDOM
            reg.allocated_by = allocated_by
            current_confirmed += 1
            confirmed_count += 1
        else:
            reg.status = WorkshopRegistrationStatus.WAITLISTED
            reg.allocation_method = AllocationMode.RANDOM
            reg.allocated_by = allocated_by
            waitlisted_count += 1
        reg.save(update_fields=['status', 'allocation_method', 'allocated_by'])

    return {'confirmed': confirmed_count, 'waitlisted': waitlisted_count}


@transaction.atomic
def run_interest_ranking_allocation(
    event,
    workshops=None,
    allocated_by: "AbstractBaseUser | None" = None,
) -> dict:
    """
    Allocate attendees across workshops for an event based on ranked interest submissions.

    Algorithm (greedy, earliest-submission-first):
    1. Collect all finalised interest submissions for the event, ordered by submitted_at.
    2. For each submission (in order), walk the attendee's ranked choices. Place the
       attendee in the first workshop that still has capacity and is in OPEN status.
    3. If no ranked workshop is available, the attendee is left unallocated (no registration
       is created from this pass — they may have an existing PENDING_ALLOCATION record).

    After placement, any remaining PENDING_ALLOCATION registrations on the target workshops
    are set to WAITLISTED.

    Args:
        event: The Event instance to process.
        workshops: Optional queryset/list to restrict allocation to a subset of workshops.
        allocated_by: Staff user triggering the allocation (recorded on each registration).

    Returns:
        dict with keys 'placed', 'waitlisted', 'unplaced'.
    """
    from apps.workshops.models.workshop import WorkshopStatus
    from apps.workshops.models.interest import WorkshopInterestSubmission

    target_workshop_ids = None
    if workshops is not None:
        target_workshop_ids = set(str(w.pk) for w in workshops)

    submissions = (
        WorkshopInterestSubmission.objects
        .filter(event=event, is_finalised=True)
        .prefetch_related('ranks__workshop')
        .order_by('submitted_at')
    )

    # Track current confirmed counts per workshop (avoid repeated DB hits)
    from apps.workshops.models.workshop import Workshop as WorkshopModel
    qs = WorkshopModel.objects.filter(event=event, status=WorkshopStatus.OPEN)
    if target_workshop_ids:
        qs = qs.filter(pk__in=target_workshop_ids)
    workshop_map = {str(w.pk): w for w in qs}
    confirmed_counts = {
        pk: w.current_registration_count
        for pk, w in workshop_map.items()
    }

    placed = 0
    unplaced = 0

    for submission in submissions:
        attendee = submission.attendee
        allocated = False

        for rank_entry in submission.ranks.all():
            ws_pk = str(rank_entry.workshop_id)
            ws = workshop_map.get(ws_pk)
            if ws is None:
                continue  # workshop not in scope or not OPEN

            cap = ws.capacity
            if cap is not None and confirmed_counts[ws_pk] >= cap:
                continue  # full — try next rank

            # Allocate
            _create_or_update_registration(
                workshop=ws,
                attendee=attendee,
                status=WorkshopRegistrationStatus.CONFIRMED,
                allocation_method=AllocationMode.INTEREST_RANKING,
                allocated_by=allocated_by,
            )
            confirmed_counts[ws_pk] += 1
            placed += 1
            allocated = True
            break

        if not allocated:
            unplaced += 1

    # Waitlist any remaining PENDING_ALLOCATION registrations on the target workshops
    waitlisted = 0
    pending_qs = WorkshopRegistration.objects.filter(
        status=WorkshopRegistrationStatus.PENDING_ALLOCATION,
        workshop__event=event,
    )
    if target_workshop_ids:
        pending_qs = pending_qs.filter(workshop_id__in=target_workshop_ids)

    waitlisted = pending_qs.update(
        status=WorkshopRegistrationStatus.WAITLISTED,
        allocation_method=AllocationMode.INTEREST_RANKING,
        allocated_by=allocated_by,
    )

    return {'placed': placed, 'waitlisted': waitlisted, 'unplaced': unplaced}
