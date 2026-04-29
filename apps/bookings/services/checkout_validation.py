"""
Checkout Validation Service

Provides comprehensive validation of checkout requests with proper separation of concerns.

This service validates:
- Booking intent status and eligibility
- Payment method configuration
- Attendee data (both existing and draft records)
- Package eligibility and pricing
- Product selections and variants
- Event questions and consent records

All validation methods raise ValidationError with field-specific error messages.
"""
import logging
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple

from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError
from djmoney.money import Money

from apps.bookings.models import BookingIntent, BookingPackage, PackageProduct
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.attendee.models.personal.dietary import DietaryRequirement
from apps.attendee.models.personal.medical import MedicalCondition
from apps.attendee.models.personal.accessibility import AccessibilityRequirement
from apps.events.models import Event, EventQuestion, EventQuestionTypeChoices
from apps.payments.models import PaymentMethod, PaymentMethodTypeChoices
from apps.common.models import Resource, VerificationStatus
from apps.attendee.models.personal.consent import Consent
from apps.users.models import CommunityUser
User = get_user_model()
logger = logging.getLogger(__name__)


class CheckoutValidationError(ValidationError):
    """Raised when checkout validation fails with specific field error."""
    pass


class CheckoutValidationService:
    """
    Service for validating checkout requests with modular, reusable validation methods.
    
    Each public method validates a specific aspect of the checkout request.
    Methods raise ValidationError with field-specific error messages.
    
    All methods are stateless and can be called independently.
    """
    
    _ALLOWED_UPLOAD_CONTENT_TYPES = {
        'application/pdf',
        'text/csv',
        'application/csv',
        'application/vnd.ms-excel',
    }
    _ALLOWED_UPLOAD_EXTENSIONS = ('.pdf', '.csv')
    _MAX_UPLOAD_FILE_SIZE_BYTES = 10 * 1024 * 1024

    @staticmethod
    def _validate_upload_file(answer: Dict[str, Any]) -> None:
        upload_file = answer.get('_upload_file')
        if not upload_file:
            return

        content_type = str(getattr(upload_file, 'content_type', '') or '').lower()
        file_name = str(getattr(upload_file, 'name', '') or '').lower()
        file_size = int(getattr(upload_file, 'size', 0) or 0)

        if file_size <= 0:
            raise ValidationError({'attendees': 'Uploaded question file is empty.'})

        if file_size > CheckoutValidationService._MAX_UPLOAD_FILE_SIZE_BYTES:
            raise ValidationError({
                'attendees': 'Uploaded question file exceeds the maximum allowed size of 10MB.'
            })

        is_image = content_type.startswith('image/')
        is_allowed_document = (
            content_type in CheckoutValidationService._ALLOWED_UPLOAD_CONTENT_TYPES
            or file_name.endswith(CheckoutValidationService._ALLOWED_UPLOAD_EXTENSIONS)
        )

        if not is_image and not is_allowed_document:
            raise ValidationError({
                'attendees': 'Unsupported question upload file type. Allowed: images, PDF, CSV.'
            })

    @staticmethod
    def validate_booking_intent(
        intent_id,
        user: Optional[CommunityUser] = None,
        allow_inactive_idempotent_replay: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> BookingIntent:
        """
        Validate booking intent exists, is active, and eligible for booking.
        
        Args:
            intent_id: UUID of the booking intent
            user: Optional user for ownership validation (if not staff)
            
        Returns:
            BookingIntent instance if valid
            
        Raises:
            ValidationError with 'booking_intent_id' field error
        """
        try:
            intent = BookingIntent.objects.get(booking_intent_id=intent_id)
        except BookingIntent.DoesNotExist:
            raise ValidationError({
                'booking_intent_id': f'BookingIntent with id {intent_id} does not exist.'
            })
        
        is_idempotent_replay = bool(
            allow_inactive_idempotent_replay
            and idempotency_key
            and intent.last_checkout_idempotency_key == idempotency_key
        )

        # Validate status
        if not intent.is_active and not is_idempotent_replay:
            raise ValidationError({
                'booking_intent_id': (
                    f'BookingIntent {intent_id} is not active. '
                    f'Status: {intent.get_status_display()}, Expired: {intent.is_expired}'
                )
            })
        
        # Validate can create booking
        if not intent.can_create_booking() and not is_idempotent_replay:
            raise ValidationError({
                'booking_intent_id': (
                    f'Cannot create booking from intent {intent_id}. '
                    f'Event may be full or closed.'
                )
            })
        
        # Validate ownership for non-staff users
        if user and not (user.is_staff or user.is_superuser):
            if not intent.made_by_id or intent.made_by_id != user.id:
                raise ValidationError({
                    'booking_intent_id': 'This booking intent does not belong to the authenticated user.'
                })
        
        return intent
    
    @staticmethod
    def validate_payment_method(method_id: int, event: Event) -> PaymentMethod:
        """
        Validate payment method exists, is active, and matches event.
        
        Args:
            method_id: ID of the payment method
            event: Event instance for cross-validation
            
        Returns:
            PaymentMethod instance if valid
            
        Raises:
            ValidationError with 'payment_method_id' field error
        """
        try:
            method = PaymentMethod.objects.get(id=method_id)
        except PaymentMethod.DoesNotExist:
            raise ValidationError({
                'payment_method_id': f'PaymentMethod with id {method_id} does not exist.'
            })
        
        if not method.is_active:
            raise ValidationError({
                'payment_method_id': f'PaymentMethod "{method.title}" is not currently active.'
            })
        
        # Validate belongs to same event
        if method.event_id != event.id:
            raise ValidationError({
                'payment_method_id': 'Payment method must belong to the same event as booking intent.'
            })
        
        return method
    
    @staticmethod
    def validate_attendee_count(attendee_count: int, expected_count: int) -> None:
        """
        Validate attendee count matches booking intent.
        
        Args:
            attendee_count: Actual attendee selections provided
            expected_count: Expected count from booking intent
            
        Raises:
            ValidationError with 'attendees' field error
        """
        if attendee_count != expected_count:
            raise ValidationError({
                'attendees': (
                    f'Expected {expected_count} attendees based on booking intent, '
                    f'but received {attendee_count} selections.'
                )
            })
    
    @staticmethod
    def validate_attendee_draft(draft: Dict[str, Any]) -> None:
        """
        Validate attendee draft data has required fields and valid values.
        
        Django model validation is applied during attendee creation,
        so this focuses on presence of required fields.
        
        Args:
            draft: Attendee draft dictionary from request
            
        Raises:
            ValidationError with 'attendees' field error
        """
        required_fields = ['first_name', 'last_name', 'date_of_birth']
        missing_fields = [f for f in required_fields if not draft.get(f)]
        
        if missing_fields:
            raise ValidationError({
                'attendees': f'Attendee draft missing required fields: {", ".join(missing_fields)}'
            })
    
    @staticmethod
    def validate_attendee_event_consistency(
        attendee: Optional[Attendee],
        draft: Optional[Dict],
        expected_event: Event
    ) -> None:
        """
        Validate attendee belongs to correct event.
        
        Args:
            attendee: Existing attendee (if provided)
            draft: Attendee draft (if provided)
            expected_event: Event that attendees must belong to
            
        Raises:
            ValidationError with 'attendees' field error
        """
        if attendee and attendee.event_id != expected_event.id:
            raise ValidationError({
                'attendees': f'Attendee {attendee.attendee_id} must belong to the same event as booking intent.'
            })
        
        if draft and draft.get('area_from'):
            if not expected_event.id:
                raise ValidationError({
                    'attendees': 'Event must be provided to validate attendee.'
                })
    
    @staticmethod
    def validate_package_eligibility(
        package: BookingPackage,
        user: CommunityUser,
        attendee: Optional[Attendee]
    ) -> None:
        """
        Validate attendee is eligible for the selected package.
        
        Args:
            package: Selected booking package
            user: User making the booking
            attendee: Attendee for this selection
            
        Raises:
            ValidationError with 'package_id' field error
        """
        # Draft attendees are validated later in checkout when a concrete attendee instance exists.
        if attendee is None:
            return

        if not package.can_use_package(user, attendee):
            raise ValidationError({
                'package_id': (
                    f'Attendee {attendee.attendee_id} is not eligible for package "{package.name}".'
                )
            })
    
    @staticmethod
    def validate_product_selections(
        product_selections: List[Dict[str, Any]],
        package: BookingPackage,
        attendee: Optional[Attendee],
        context_obj: Optional[Any] = None
    ) -> None:
        """
        Validate product selections belong to package and attendee can purchase them.
        
        Args:
            product_selections: List of product selection dicts
            package: Parent booking package
            attendee: Attendee making selections
            context_obj: Optional context object for pricing (from viewset)
            
        Raises:
            ValidationError with 'product_selections' field errors
        """
        for idx, selection in enumerate(product_selections):
            package_product_id = selection.get('package_product_id')
            variant_id = selection.get('variant_id')
            quantity = int(selection.get('quantity', 0))
            
            # Validate product exists and belongs to package
            try:
                from apps.products.models import ProductVariant
                
                pkg_product = PackageProduct.objects.get(id=package_product_id)
            except PackageProduct.DoesNotExist:
                raise ValidationError({
                    'product_selections': f'PackageProduct {package_product_id} not found.'
                })
            
            if pkg_product.booking_package_id != package.id:
                raise ValidationError({
                    'product_selections': (
                        f'PackageProduct {package_product_id} does not belong to package {package.id}.'
                    )
                })
            
            # Validate variant exists
            try:
                variant = ProductVariant.objects.get(variant_id=variant_id)
            except ProductVariant.DoesNotExist:
                raise ValidationError({
                    'product_selections': f'ProductVariant {variant_id} not found.'
                })
            
            if variant.product_id != pkg_product.product_id:
                raise ValidationError({
                    'product_selections': (
                        f'ProductVariant {variant_id} does not belong to '
                        f'product {pkg_product.product_id}.'
                    )
                })
            
            # Attendee-specific checks require a resolved attendee instance.
            if attendee is not None:
                if not variant.can_attendee_purchase(attendee):
                    raise ValidationError({
                        'product_selections': (
                            f'Attendee {attendee.attendee_id} is not eligible for '
                            f'variant {variant_id}.'
                        )
                    })

                try:
                    variant.can_attendee_purchase_quantity(attendee, quantity, raise_exception=True)
                except DjangoValidationError as exc:
                    raise ValidationError({
                        'product_selections': f'Quantity validation failed: {str(exc)}'
                    })
    
    @staticmethod
    def validate_consent_records(
        consents: List[Dict[str, Any]],
        event: Event
    ) -> None:
        """
        Validate consent records exist, are not duplicated, and required consents given.
        
        Args:
            consents: List of consent records from draft
            event: Event for consent validation
            
        Raises:
            ValidationError with 'attendees' field error
        """
        required_consent_ids = set(
            Consent.objects.filter(event=event, required=True, active=True)
            .values_list('id', flat=True)
        )

        if not consents:
            if required_consent_ids:
                raise ValidationError({
                    'attendees': f'Missing required consents: {sorted(required_consent_ids)}'
                })
            return
        
        consent_ids = [item.get('consent_id') for item in consents]
        
        # Check for duplicates
        if len(consent_ids) != len(set(consent_ids)):
            raise ValidationError({
                'attendees': 'Duplicate consent entries detected.'
            })
        
        # Validate all consent IDs exist in event
        valid_consents = set(
            Consent.objects.filter(event=event, id__in=consent_ids)
            .values_list('id', flat=True)
        )
        invalid_consents = set(consent_ids) - valid_consents
        if invalid_consents:
            raise ValidationError({
                'attendees': f'Invalid consent IDs: {sorted(invalid_consents)}'
            })
        
        # Validate required consents are given
        consent_given_ids = {
            item.get('consent_id')
            for item in consents
            if item.get('consent_given') is True
        }
        missing_consents = required_consent_ids - consent_given_ids
        if missing_consents:
            raise ValidationError({
                'attendees': f'Missing required consents: {sorted(missing_consents)}'
            })
    
    @staticmethod
    def validate_question_answers(
        answers: List[Dict[str, Any]],
        event: Event
    ) -> None:
        """
        Validate event question answers are valid, complete, and required questions answered.
        
        Args:
            answers: List of question answer records from draft
            event: Event for question validation
            
        Raises:
            ValidationError with 'attendees' field error
        """
        required_question_ids = set(
            EventQuestion.objects.filter(event=event, required=True)
            .values_list('id', flat=True)
        )

        if not answers:
            if required_question_ids:
                raise ValidationError({
                    'attendees': f'Required questions not answered: {sorted(required_question_ids)}'
                })
            return
        
        question_ids = [item.get('question_id') for item in answers]
        
        # Check for duplicates
        if len(question_ids) != len(set(question_ids)):
            raise ValidationError({
                'attendees': 'Duplicate question answers detected.'
            })
        
        # Validate all questions exist and belong to event
        answered_questions = {}
        for answer in answers:
            question_id = answer.get('question_id')
            
            try:
                question = EventQuestion.objects.get(id=question_id)
            except EventQuestion.DoesNotExist:
                raise ValidationError({
                    'attendees': f'Question {question_id} does not exist.'
                })
            
            if question.event_id != event.id:
                raise ValidationError({
                    'attendees': 'Question must belong to the same event as booking intent.'
                })
            
            answered_questions[question_id] = question
        
        # Validate answer content per question type
        for answer in answers:
            question_id = answer.get('question_id')
            question = answered_questions[question_id]
            
            selected_option_ids = answer.get('selected_option_ids', [])
            upload_resource_id = answer.get('upload_resource_id')
            upload_url = answer.get('upload_url')
            answer_text = answer.get('answer_text')
            upload_file = answer.get('_upload_file')
            
            # Validate upload resource if provided
            if upload_resource_id:
                try:
                    resource = Resource.objects.get(id=upload_resource_id)
                except Resource.DoesNotExist:
                    raise ValidationError({
                        'attendees': f'Upload resource {upload_resource_id} does not exist.'
                    })
                
                # Verify resource belongs to event
                if (resource.target_type.model != 'event' or 
                    str(resource.target_id) != str(event.id)):
                    raise ValidationError({
                        'attendees': 'Upload resource must belong to the same event.'
                    })

            if upload_file and (upload_resource_id or upload_url):
                raise ValidationError({
                    'attendees': (
                        f'Question {question_id} cannot use multipart upload and upload_resource_id/upload_url together.'
                    )
                })

            if upload_file and question.question_type != EventQuestionTypeChoices.UPLOAD:
                raise ValidationError({
                    'attendees': f'Question {question_id} does not accept file uploads.'
                })

            CheckoutValidationService._validate_upload_file(answer)
            
            # Validate per question type
            if question.question_type in [
                EventQuestionTypeChoices.SINGLE_CHOICE,
                EventQuestionTypeChoices.MULTIPLE_CHOICE
            ]:
                if not selected_option_ids:
                    raise ValidationError({
                        'attendees': f'Question {question_id} requires selected options.'
                    })
                
                valid_option_ids = set(question.options.values_list('id', flat=True))
                invalid_options = set(selected_option_ids) - valid_option_ids
                if invalid_options:
                    raise ValidationError({
                        'attendees': (
                            f'Invalid option IDs {sorted(invalid_options)} '
                            f'for question {question_id}.'
                        )
                    })
            
            elif question.question_type in [
                EventQuestionTypeChoices.SHORT_ANSWER,
                EventQuestionTypeChoices.LONG_ANSWER,
                EventQuestionTypeChoices.UPLOAD,
            ]:
                if not answer_text and not upload_resource_id and not upload_url and not upload_file:
                    raise ValidationError({
                        'attendees': f'Question {question_id} (text) requires answer text.'
                    })
            
            elif question.question_type == EventQuestionTypeChoices.SLIDER:
                if answer_text:
                    try:
                        float(answer_text)
                    except (ValueError, TypeError):
                        raise ValidationError({
                            'attendees': f'Question {question_id} (numeric) requires valid number.'
                        })
            
            # Validate required questions have answers
            if question.required:
                has_content = bool(
                    answer_text or selected_option_ids or 
                    upload_resource_id or upload_url or upload_file
                )
                if not has_content:
                    raise ValidationError({
                        'attendees': f'Required question {question_id} has no answer.'
                    })

        answered_question_ids = set(question_ids)
        missing_required_questions = required_question_ids - answered_question_ids
        if missing_required_questions:
            raise ValidationError({
                'attendees': f'Required questions not answered: {sorted(missing_required_questions)}'
            })
    
    @staticmethod
    def validate_checkout_request(
        intent_id,
        method_id: Optional[int],
        attendee_selections: List[Dict[str, Any]],
        user: Optional[CommunityUser] = None,
        allow_inactive_idempotent_replay: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[BookingIntent, Optional[PaymentMethod]]:
        """
        Comprehensive validation of entire checkout request.
        
        Validates:
        - Booking intent eligibility
        - Payment method configuration
        - Attendee count
        - All attendee data and consistency
        - Answer consents and questions
        
        Args:
            intent_id: UUID of booking intent
            method_id: Optional ID of payment method
            attendee_selections: List of attendee selection dicts
            user: Authenticated user (for ownership validation)
            
        Returns:
            Tuple of (BookingIntent, PaymentMethod|None) if valid
            
        Raises:
            ValidationError with field-specific errors
        """
        # Validate intent
        intent = CheckoutValidationService.validate_booking_intent(
            intent_id,
            user,
            allow_inactive_idempotent_replay=allow_inactive_idempotent_replay,
            idempotency_key=idempotency_key,
        )
        event = intent.event
        
        # Validate payment method only when explicitly provided.
        # Free checkouts can defer this requirement to the view after pricing is computed.
        method = None
        if method_id not in (None, 0) and method_id > 0:
            method = CheckoutValidationService.validate_payment_method(method_id, event)
        
        # Validate attendee count
        CheckoutValidationService.validate_attendee_count(
            len(attendee_selections),
            intent.intended_ticket_count
        )
        
        # Validate each attendee selection
        event_ids = set()
        for selection in attendee_selections:
            attendee = selection.get('_attendee')
            draft = selection.get('_attendee_draft')
            
            # At least one should be provided
            if not attendee and not draft:
                raise ValidationError({
                    'attendees': 'Each selection must have either attendee_id or attendee_draft.'
                })
            
            # Validate attendee event consistency
            CheckoutValidationService.validate_attendee_event_consistency(
                attendee, draft, event
            )
            
            # Validate draft if provided
            if draft:
                CheckoutValidationService.validate_attendee_draft(draft)
                
                # Validate questions and consents for draft attendee
                CheckoutValidationService.validate_consent_records(
                    draft.get('consents', []),
                    event
                )
                CheckoutValidationService.validate_question_answers(
                    draft.get('question_answers', []),
                    event
                )
            
            # Validate package and products
            package = selection.get('_package')
            if package:
                CheckoutValidationService.validate_package_eligibility(
                    package, user, attendee
                )
                
                if selection.get('product_selections'):
                    CheckoutValidationService.validate_product_selections(
                        selection['product_selections'],
                        package,
                        attendee
                    )
        
        return intent, method
