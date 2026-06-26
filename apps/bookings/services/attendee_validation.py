from typing import Any, Dict, List, Optional, Set, Tuple

from django.db.models import Q
from django.contrib.auth.models import User  

from apps.attendee.models import Attendee, AttendeeRelationship, AttendeeStatus
from apps.events.models import Event

def normalise_text(value: Optional[str]) -> str:
    '''
    Normalise a text value by stripping whitespace and converting to lowercase.
    '''
    return str(value or "").strip().lower()

def normalise_phone(value: Optional[str]) -> str:
    '''
    Normalise a phone number by removing all non-digit characters except for the leading '+'.   
    '''
    raw = str(value or "")
    return "".join(ch for ch in raw if ch.isdigit() or ch == "+")
class AttendeePrecheckValidationService:
    """
    Centralised attendee precheck/guardrail validation for bookings.
    """

    DUPLICATE_EMAIL = "DUPLICATE_EMAIL"
    DUPLICATE_PHONE = "DUPLICATE_PHONE"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    SELF_ALREADY_REGISTERED = "SELF_ALREADY_REGISTERED"
    MAX_PER_BOOKING_EXCEEDED = "MAX_PER_BOOKING_EXCEEDED"
    MAX_PER_USER_EXCEEDED = "MAX_PER_USER_EXCEEDED"
    DUPLICATE_IN_REQUEST = "DUPLICATE_IN_REQUEST"

    _DUPLICATE_BLOCKING_STATUSES = {
        AttendeeStatus.PENDING_PAYMENT,
        AttendeeStatus.REGISTERED,
        AttendeeStatus.CHECKED_IN,
        AttendeeStatus.WHITELISTED,
    }

    _COUNTED_USER_STATUSES = {
        AttendeeStatus.REGISTERED,
        AttendeeStatus.CHECKED_IN,
    }

    @classmethod
    def _attendee_payload_signature(cls, attendee_data: Dict[str, Any]) -> Tuple[str, str, str]:
        '''
        Args:
            attendee_data (dict): A dictionary containing attendee information.
        Returns:
            tuple[str, str, str]: A tuple containing the normalized first name, last name, and date of birth.   
        '''
        first_name = normalise_text(attendee_data.get("first_name"))
        last_name = normalise_text(attendee_data.get("last_name"))
        date_of_birth = str(attendee_data.get("date_of_birth") or "").strip()
        return first_name, last_name, date_of_birth

    @classmethod
    def _extract_attendee_data(cls, selection: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Args:
            selection (dict): A dictionary representing an attendee selection, which may contain either an "_attendee" object or an "_attendee_draft" dictionary.
        Returns:
            dict: A dictionary containing the extracted attendee data, including first name, last name, email, phone number, date of birth, and relationship to user. If neither an "_attendee" object nor an "_attendee_draft" is present, returns an empty dictionary.
        '''
        attendee_obj = selection.get("_attendee")
        if attendee_obj:
            return {
                "first_name": attendee_obj.first_name,
                "last_name": attendee_obj.last_name,
                "email": attendee_obj.email,
                "phone_number": attendee_obj.phone_number,
                "date_of_birth": attendee_obj.date_of_birth,
                "relationship_to_user": attendee_obj.relationship_to_user,
            }
        return selection.get("_attendee_draft") or {}

    @classmethod
    def validate(cls, *, event: Event, user: User, attendee_selections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate attendee selections against duplicate and event limit policies.
        Returns structured payload suitable for API response and serializer errors.
        Args:
            event: The event instance for which the validation is being performed.
            user: The user instance for which the validation is being performed.
            attendee_selections: A list of dictionaries representing attendee selections.
        Returns:
            dict: A dictionary containing booking and attendee errors, if any.
        """
        settings = getattr(event, "settings", None)
        max_per_booking = getattr(settings, "max_attendees_per_booking", None)
        max_per_user = getattr(settings, "max_attendees_per_user", None)

        booking_errors: List[Dict[str, str]] = []
        attendee_errors: List[Dict[str, Any]] = []

        if isinstance(max_per_booking, int) and len(attendee_selections) > max_per_booking:
            booking_errors.append({
                "code": cls.MAX_PER_BOOKING_EXCEEDED,
                "message": (
                    f"This event allows at most {max_per_booking} attendees per booking. "
                    f"You submitted {len(attendee_selections)} attendee(s)."
                ),
            })

        existing_attendee_ids: Set[int] = {
            selection["_attendee"].id
            for selection in attendee_selections
            if selection.get("_attendee") is not None
        }

        counted_user_attendees_qs = Attendee.objects.filter(
            event=event,
            booking__made_by=user,
            status__in=cls._COUNTED_USER_STATUSES,
            deleted_at__isnull=True,
        ).exclude(id__in=existing_attendee_ids)

        existing_user_attendee_count = counted_user_attendees_qs.count()
        projected_user_attendee_count = existing_user_attendee_count + len(attendee_selections)

        if isinstance(max_per_user, int) and projected_user_attendee_count > max_per_user:
            booking_errors.append({
                "code": cls.MAX_PER_USER_EXCEEDED,
                "message": (
                    f"This event allows at most {max_per_user} attendees per user. "
                    f"You already have {existing_user_attendee_count} and this request would make {projected_user_attendee_count}."
                ),
            })

        seen_emails: Set[str] = set()
        seen_phones: Set[str] = set()
        seen_identity: Set[Tuple[str, str, str]] = set()

        for index, selection in enumerate(attendee_selections):
            payload = cls._extract_attendee_data(selection)
            row_codes: List[str] = []
            row_messages: List[str] = []

            email_norm = normalise_text(payload.get("email"))
            phone_norm = normalise_phone(payload.get("phone_number"))
            identity_signature = cls._attendee_payload_signature(payload)

            if email_norm and email_norm in seen_emails:
                row_codes.append(cls.DUPLICATE_IN_REQUEST)
                row_messages.append("Duplicate email found in this request.")
            if phone_norm and phone_norm in seen_phones:
                row_codes.append(cls.DUPLICATE_IN_REQUEST)
                row_messages.append("Duplicate phone number found in this request.")
            if all(identity_signature) and identity_signature in seen_identity:
                row_codes.append(cls.DUPLICATE_IN_REQUEST)
                row_messages.append(
                    "Duplicate attendee identity (first name, last name, date of birth) found in this request."
                )

            if email_norm:
                seen_emails.add(email_norm)
            if phone_norm:
                seen_phones.add(phone_norm)
            if all(identity_signature):
                seen_identity.add(identity_signature)

            duplicate_qs = Attendee.objects.filter(
                event=event,
                status__in=cls._DUPLICATE_BLOCKING_STATUSES,
                deleted_at__isnull=True,
            ).exclude(id__in=existing_attendee_ids)

            duplicate_query = Q()
            if email_norm:
                duplicate_query |= Q(email__iexact=email_norm)
            if phone_norm:
                duplicate_query |= Q(phone_number__iexact=payload.get("phone_number"))

            first_name, last_name, dob = identity_signature
            if first_name and last_name and dob:
                duplicate_query |= (
                    Q(first_name__iexact=payload.get("first_name"))
                    & Q(last_name__iexact=payload.get("last_name"))
                    & Q(date_of_birth=payload.get("date_of_birth"))
                )

            if duplicate_query:
                duplicate_match = duplicate_qs.filter(duplicate_query).first()
                if duplicate_match:
                    if email_norm and duplicate_match.email and duplicate_match.email.lower() == email_norm:
                        row_codes.append(cls.DUPLICATE_EMAIL)
                        row_messages.append("An attendee with this email is already registered for this event.")
                    if phone_norm and duplicate_match.phone_number:
                        if normalise_phone(duplicate_match.phone_number) == phone_norm:
                            row_codes.append(cls.DUPLICATE_PHONE)
                            row_messages.append("An attendee with this phone number is already registered for this event.")
                    if (
                        duplicate_match.first_name
                        and duplicate_match.last_name
                        and duplicate_match.date_of_birth
                        and normalise_text(duplicate_match.first_name) == first_name
                        and normalise_text(duplicate_match.last_name) == last_name
                        and str(duplicate_match.date_of_birth) == dob
                    ):
                        row_codes.append(cls.DUPLICATE_IDENTITY)
                        row_messages.append(
                            "An attendee with the same first name, last name, and date of birth already exists for this event."
                        )

            relationship = payload.get("relationship_to_user")
            if relationship == AttendeeRelationship.SELF:
                self_exists = Attendee.objects.filter(
                    event=event,
                    user=user,
                    relationship_to_user=AttendeeRelationship.SELF,
                    status__in=cls._DUPLICATE_BLOCKING_STATUSES,
                    deleted_at__isnull=True,
                ).exclude(id__in=existing_attendee_ids).exists()
                if self_exists:
                    row_codes.append(cls.SELF_ALREADY_REGISTERED)
                    row_messages.append(
                        "You are already registered as self for this event. You can still register other attendees."
                    )

            if row_codes:
                attendee_errors.append({
                    "index": index,
                    "codes": sorted(set(row_codes)),
                    "messages": row_messages,
                })

        return {
            "valid": not booking_errors and not attendee_errors,
            "booking_errors": booking_errors,
            "attendee_errors": attendee_errors,
            "limits": {
                "max_attendees_per_booking": max_per_booking,
                "max_attendees_per_user": max_per_user,
                "requested_attendee_count": len(attendee_selections),
                "existing_user_attendee_count": existing_user_attendee_count,
                "projected_user_attendee_count": projected_user_attendee_count,
                "remaining_slots_for_user": (
                    None
                    if not isinstance(max_per_user, int)
                    else max(0, max_per_user - projected_user_attendee_count)
                ),
            },
        }
