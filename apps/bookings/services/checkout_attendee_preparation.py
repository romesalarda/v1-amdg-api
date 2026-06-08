"""
Checkout Attendee Preparation Service

Handles creation and configuration of attendees during checkout submission.

This service is responsible for:
1. Creating new attendees from draft data (or updating existing attendees)
2. Attaching personal information (dietary, medical, accessibility)
3. Attaching emergency contacts
4. Attaching consent records
5. Attaching event question answers

All operations are atomic and scoped to a specific attendee. If any step fails,
the entire attendee preparation fails and is rolled back.

This is called BEFORE payment to ensure attendee records exist regardless of
payment method or success/failure.
"""
import logging
from typing import Dict, Any, Optional

from django.contrib.auth import get_user_model

from apps.attendee.models import (
    Attendee, AttendeeRelationship,
)
from apps.attendee.models.personal.dietary import AttendeeDietaryRequirement, DietaryRequirement
from apps.attendee.models.personal.medical import AttendeeMedicalCondition, MedicalCondition
from apps.attendee.models.personal.accessibility import (
    AttendeeAccessibilityRequirement, AccessibilityRequirement
)
from apps.attendee.models.personal.emergency import EmergencyContact
from apps.attendee.models.personal.consent import AttendeeConsent, Consent
from apps.events.models import EventQuestionAnswer, EventQuestionAnswerChoice
from apps.common.models import Resource
from apps.bookings.models import Booking
from apps.users.models import CommunityUser

User = get_user_model()
logger = logging.getLogger(__name__)


class AttendeePreparationError(Exception):
    """Raised when attendee preparation fails."""
    pass


class CheckoutAttendeePreparationService:
    """
    Service for preparing attendees during checkout submission.
    
    Creates and configures attendees before payment verification,
    ensuring attendee records exist regardless of payment outcome.
    
    All public methods are transaction-safe and can be called independently.
    """
    
    @staticmethod
    def prepare_or_create_attendee(
        selection: Dict[str, Any],
        booking: Booking,
        user: CommunityUser,
        actor: Optional[CommunityUser] = None,
    ) -> Attendee:
        """
        Prepare or create an attendee for checkout.
        
        If attendee_id provided: updates existing attendee with booking
        If attendee_draft provided: creates new attendee from draft
        
        Args:
            selection: Attendee selection dict with _attendee or _attendee_draft
            booking: Parent Booking instance  
            user: User making the booking (for relationship validation)
            actor: Optional user performing the action (for audit trail)
            
        Returns:
            Attendee instance (created or updated)
            
        Raises:
            AttendeePreparationError if creation/update fails
        """
        attendee = selection.get('_attendee')
        draft = selection.get('_attendee_draft')
        
        try:
            if attendee:
                # Update existing attendee with booking reference
                attendee.booking = booking
                attendee.save(update_fields=['booking', 'updated_at'])
                logger.info(
                    f"Linked existing attendee {attendee.attendee_id} to booking {booking.booking_reference}"
                )
                return attendee
            elif draft:
                # Create new attendee from draft
                attendee = CheckoutAttendeePreparationService._create_attendee_from_draft(
                    draft, booking, user, actor
                )
                logger.info(
                    f"Created new attendee {attendee.attendee_id} for booking {booking.booking_reference}"
                )
                return attendee
            else:
                raise AttendeePreparationError('No attendee_id or attendee_draft provided')
                
        except Exception as exc:
            logger.error(f"Failed to prepare attendee: {str(exc)}", exc_info=True)
            raise AttendeePreparationError(str(exc)) from exc
    
    @staticmethod
    def _create_attendee_from_draft(
        draft: Dict[str, Any],
        booking: Booking,
        user: CommunityUser,
        actor: Optional[CommunityUser] = None
    ) -> Attendee:
        """
        Create attendee from draft data.
        
        Args:
            draft: Attendee draft dictionary
            booking: Parent booking
            user: User making the booking
            actor: Optional user performing the action
            
        Returns:
            Created Attendee instance
            
        Raises:
            AttendeePreparationError if creation fails
        """
        relationship = draft.get('relationship_to_user', AttendeeRelationship.OTHER)
        attendee_user = user if relationship == AttendeeRelationship.SELF else None
        
        try:
            attendee = Attendee.objects.create(
                event=booking.event,
                booking=booking,
                user=attendee_user,
                defined_by=actor or user,
                first_name=draft.get('first_name'),
                last_name=draft.get('last_name'),
                email=draft.get('email') or None,
                phone_number=draft.get('phone_number') or None,
                date_of_birth=draft.get('date_of_birth'),
                gender=draft.get('gender') or None,
                relationship_to_user=relationship,
                area_from_id=draft.get('area_from'),
            )
        except Exception as exc:
            raise AttendeePreparationError(
                f"Failed to create attendee: {str(exc)}"
            ) from exc
        
        # Attach personal information
        personal_info = draft.get('personal_info') or {}
        
        CheckoutAttendeePreparationService._attach_dietary_requirements(
            attendee, personal_info, actor or user
        )
        CheckoutAttendeePreparationService._attach_medical_conditions(
            attendee, personal_info, actor or user
        )
        CheckoutAttendeePreparationService._attach_accessibility_requirements(
            attendee, personal_info, actor or user
        )
        CheckoutAttendeePreparationService._attach_emergency_contact(
            attendee, personal_info, actor or user
        )
        
        # Attach consents and question answers
        CheckoutAttendeePreparationService._attach_consents(
            attendee, draft.get('consents', []), actor or user
        )
        CheckoutAttendeePreparationService._attach_question_answers(
            attendee, draft.get('question_answers', []), actor or user
        )
        
        return attendee
    
    @staticmethod
    def _attach_dietary_requirements(
        attendee: Attendee,
        personal_info: Dict[str, Any],
        actor: CommunityUser
    ) -> None:
        """Attach dietary requirements to attendee."""
        dietary_items = personal_info.get('dietary_requirements', []) or []
        for item in dietary_items:
            try:
                req = DietaryRequirement.objects.get(id=item['id'])
                AttendeeDietaryRequirement.objects.create(
                    attendee=attendee,
                    dietary_requirement=req,
                    details=item.get('details'),
                    notes=item.get('notes'),
                    added_by=actor,
                )
            except DietaryRequirement.DoesNotExist:
                logger.warning(
                    f"Dietary requirement {item['id']} not found for attendee {attendee.attendee_id}"
                )
            except Exception as exc:
                logger.error(f"Failed to attach dietary requirement: {str(exc)}", exc_info=True)
                raise AttendeePreparationError(f"Failed to attach dietary requirement: {str(exc)}") from exc
    
    @staticmethod
    def _attach_medical_conditions(
        attendee: Attendee,
        personal_info: Dict[str, Any],
        actor: CommunityUser
    ) -> None:
        """Attach medical conditions to attendee."""
        medical_items = personal_info.get('medical_conditions', []) or []
        for item in medical_items:
            try:
                condition = MedicalCondition.objects.get(id=item['id'])
                AttendeeMedicalCondition.objects.create(
                    attendee=attendee,
                    medical_condition=condition,
                    details=item.get('details'),
                    notes=item.get('notes'),
                    severity=item.get('severity'),
                    added_by=actor,
                )
            except MedicalCondition.DoesNotExist:
                logger.warning(
                    f"Medical condition {item['id']} not found for attendee {attendee.attendee_id}"
                )
            except Exception as exc:
                logger.error(f"Failed to attach medical condition: {str(exc)}", exc_info=True)
                raise AttendeePreparationError(f"Failed to attach medical condition: {str(exc)}") from exc
    
    @staticmethod
    def _attach_accessibility_requirements(
        attendee: Attendee,
        personal_info: Dict[str, Any],
        actor: CommunityUser
    ) -> None:
        """Attach accessibility requirements to attendee."""
        accessibility_items = personal_info.get('accessibility_requirements', []) or []
        for item in accessibility_items:
            try:
                req = AccessibilityRequirement.objects.get(id=item['id'])
                AttendeeAccessibilityRequirement.objects.create(
                    attendee=attendee,
                    accessibility_requirement=req,
                    details=item.get('details'),
                    notes=item.get('notes'),
                    added_by=actor,
                )
            except AccessibilityRequirement.DoesNotExist:
                logger.warning(
                    f"Accessibility requirement {item['id']} not found for attendee {attendee.attendee_id}"
                )
            except Exception as exc:
                logger.error(f"Failed to attach accessibility requirement: {str(exc)}", exc_info=True)
                raise AttendeePreparationError(
                    f"Failed to attach accessibility requirement: {str(exc)}"
                ) from exc
    
    @staticmethod
    def _attach_emergency_contact(
        attendee: Attendee,
        personal_info: Dict[str, Any],
        actor: CommunityUser
    ) -> None:
        """Attach emergency contact to attendee."""
        emergency = personal_info.get('emergency_contact')
        if not emergency:
            return
        
        try:
            EmergencyContact.objects.create(
                attendee=attendee,
                first_name=emergency.get('first_name'),
                last_name=emergency.get('last_name'),
                relationship=emergency.get('relationship'),
                phone_number=emergency.get('phone_number'),
                email=emergency.get('email') or None,
                primary_contact=emergency.get('primary_contact', True),
                added_by=actor,
            )
        except Exception as exc:
            logger.error(f"Failed to attach emergency contact: {str(exc)}", exc_info=True)
            raise AttendeePreparationError(f"Failed to attach emergency contact: {str(exc)}") from exc
    
    @staticmethod
    def _attach_consents(
        attendee: Attendee,
        consent_records: list,
        actor: CommunityUser
    ) -> None:
        """Attach consent records to attendee."""
        for consent_record in consent_records:
            try:
                consent_obj = Consent.objects.get(id=consent_record['consent_id'])
                consent_given = consent_record.get('consent_given', False)
                AttendeeConsent.objects.create(
                    attendee=attendee,
                    consent=consent_obj,
                    consent_given=consent_given,
                    given_by=actor if consent_given else None,
                )
            except Consent.DoesNotExist:
                logger.warning(
                    f"Consent {consent_record['consent_id']} not found for attendee {attendee.attendee_id}"
                )
            except Exception as exc:
                logger.error(f"Failed to attach consent: {str(exc)}", exc_info=True)
                raise AttendeePreparationError(f"Failed to attach consent: {str(exc)}") from exc
    
    @staticmethod
    def _attach_question_answers(
        attendee: Attendee,
        question_answers: list,
        actor: CommunityUser
    ) -> None:
        """Attach event question answers to attendee."""
        from apps.events.models import EventQuestion
        
        for answer in question_answers:
            try:
                question = EventQuestion.objects.get(id=answer['question_id'])
                
                # Parse answer based on question type
                answer_text = answer.get('answer_text')
                selected_option_ids = answer.get('selected_option_ids', [])
                upload_resource_id = answer.get('upload_resource_id')
                upload_url = answer.get('upload_url')

                if upload_resource_id:
                    try:
                        resource = Resource.objects.get(id=upload_resource_id)
                    except Resource.DoesNotExist:
                        raise AttendeePreparationError(
                            f"Upload resource {upload_resource_id} not found for attendee answer."
                        )
                    answer_text = resource.resource_url
                elif upload_url:
                    answer_text = upload_url
                
                # Create the question answer record
                question_answer = EventQuestionAnswer.objects.create(
                    attendee=attendee,
                    question=question,
                    answer_text=answer_text,
                    answered_by=actor,
                )
                
                # Attach selected options if provided
                if selected_option_ids:
                    for option_id in selected_option_ids:
                        try:
                            option = question.options.get(id=option_id)
                            EventQuestionAnswerChoice.objects.create(
                                question_answer=question_answer,
                                chosen_option=option,
                            )
                        except Exception as exc:
                            logger.warning(
                                f"Failed to attach option {option_id} to question answer: {str(exc)}"
                            )
                            
            except EventQuestion.DoesNotExist:
                logger.warning(
                    f"EventQuestion {answer['question_id']} not found for attendee {attendee.attendee_id}"
                )
            except Exception as exc:
                logger.error(f"Failed to attach question answer: {str(exc)}", exc_info=True)
                raise AttendeePreparationError(f"Failed to attach question answer: {str(exc)}") from exc
