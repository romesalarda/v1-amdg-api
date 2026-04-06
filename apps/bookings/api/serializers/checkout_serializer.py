"""
Checkout Serializers with comprehensive schema documentation.

This module contains all serializers for the checkout flow with extensive
drf_spectacular decorators for OpenAPI schema generation.

Serializers:
    - ProductSelectionSerializer: Product variant selection
    - EmergencyContactDraftSerializer: Emergency contact data
    - PersonalInfoItemSerializer: Personal requirement items
    - MedicalConditionItemSerializer: Medical condition with severity
    - AttendeePersonalInfoDraftSerializer: Complete personal info
    - AttendeeConsentDraftSerializer: Consent records
    - EventQuestionAnswerDraftSerializer: Question answers with uploads
    - AttendeeDraftSerializer: Complete attendee draft
    - AttendeeCheckoutSerializer: Attendee selection for checkout
    - CheckoutSerializer: Main checkout request
    - CheckoutPreviewSerializer: Preview without payment
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.bookings.models import (
    BookingIntent, BookingPackage, PackageProduct
)
from apps.attendee.models import Attendee, AttendeeRelationship
from apps.events.models import EventQuestion, EventQuestionTypeChoices
from apps.payments.models import BankTransferEvidence


# ============================================================================
# PRODUCT SELECTION SERIALIZERS
# ============================================================================

class ProductSelectionSerializer(serializers.Serializer):
    """
    Serializer for product variant selection within a booking package.
    
    Validates:
    - PackageProduct exists and belongs to package
    - ProductVariant exists and belongs to product
    - Variant is purchasable
    - Quantity does not exceed package limits
    
    Example:
        {
            "package_product_id": 1,
            "variant_id": "550e8400-e29b-41d4-a716-446655440000",
            "quantity": 2
        }
    """
    
    package_product_id = serializers.IntegerField(
        help_text="ID of the PackageProduct this selection is for"
    )
    variant_id = serializers.UUIDField(
        help_text="UUID of the ProductVariant being selected"
    )
    quantity = serializers.IntegerField(
        min_value=1,
        default=1,
        help_text="Quantity to order (must not exceed package_product.quantity_per_attendee)"
    )
    
    def validate(self, attrs):
        """Validate that quantity doesn't exceed package limits."""
        from apps.products.models import ProductVariant
        
        package_product_id = attrs.get('package_product_id')
        variant_id = attrs.get('variant_id')
        quantity = attrs.get('quantity')
        
        # Validate PackageProduct exists
        try:
            package_product = PackageProduct.objects.get(id=package_product_id)
        except PackageProduct.DoesNotExist:
            raise serializers.ValidationError({
                'package_product_id': f'PackageProduct with id {package_product_id} does not exist.'
            })

        # Validate ProductVariant exists
        try:
            variant = ProductVariant.objects.get(variant_id=variant_id)
        except ProductVariant.DoesNotExist:
            raise serializers.ValidationError({
                'variant_id': f'ProductVariant with id {variant_id} does not exist.'
            })
        
        if variant.product_id != package_product.product_id:
            raise serializers.ValidationError({
                'variant_id': f'Variant does not belong to product {package_product.product.title}'
            })

        if not variant.is_purchasable:
            raise serializers.ValidationError({
                'variant_id': f'Variant {variant_id} is not currently purchasable.'
            })
        
        # Strict enforcement: quantity must not exceed package limit
        if quantity > package_product.quantity_per_attendee:
            raise serializers.ValidationError({
                'quantity': (
                    f'Quantity {quantity} exceeds package limit of '
                    f'{package_product.quantity_per_attendee}. '
                    'To order more, place a separate order after checkout.'
                )
            })
        
        # Store validated objects for later use
        attrs['_package_product'] = package_product
        attrs['_variant'] = variant
        
        return attrs


# ============================================================================
# PERSONAL INFO SERIALIZERS
# ============================================================================

class EmergencyContactDraftSerializer(serializers.Serializer):
    """
    Emergency contact information for attendee.
    
    Required for minors (under 18). Validates phone number format
    and email format.
    
    Example:
        {
            "first_name": "Jane",
            "last_name": "Doe",
            "relationship": "parent",
            "phone_number": "+44 1234 567890",
            "email": "jane@example.com",
            "primary_contact": true
        }
    """
    first_name = serializers.CharField(
        max_length=150,
        help_text="First name of emergency contact"
    )
    last_name = serializers.CharField(
        max_length=150,
        help_text="Last name of emergency contact"
    )
    relationship = serializers.ChoiceField(
        choices=['parent', 'sibling', 'child', 'spouse', 'friend', 'other'],
        help_text="Relationship to attendee"
    )
    phone_number = serializers.CharField(
        max_length=20,
        help_text="Phone number of emergency contact (international format supported)"
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Email address of emergency contact (optional)"
    )
    primary_contact = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether this is the primary emergency contact"
    )


class PersonalInfoItemSerializer(serializers.Serializer):
    """
    Generic personal requirement item (dietary, accessibility, etc).
    
    Example:
        {
            "id": 1,
            "details": "Gluten-free",
            "notes": "Also avoid cross-contamination"
        }
    """
    id = serializers.IntegerField(
        help_text="ID of the requirement (dietary requirement ID, etc)"
    )
    details = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Additional details about this requirement"
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Notes or special instructions for this requirement"
    )


class MedicalConditionItemSerializer(PersonalInfoItemSerializer):
    """
    Medical condition item with severity level.
    
    Example:
        {
            "id": 3,
            "details": "Nut allergy - severe",
            "notes": "Keep EpiPen on hand",
            "severity": "severe"
        }
    """
    severity = serializers.ChoiceField(
        choices=['mild', 'moderate', 'severe'],
        required=False,
        allow_null=True,
        help_text="Severity level of the medical condition"
    )


class AttendeePersonalInfoDraftSerializer(serializers.Serializer):
    """
    Complete personal information payload for attendee.
    
    Includes dietary restrictions, medical conditions, accessibility needs,
    and emergency contact. Most fields are optional unless marked as required
    (e.g., emergency contact for minors).
    
    Example:
        {
            "dietary_requirements": [
                {"id": 1, "details": "Vegetarian", "notes": "No substitute needed"}
            ],
            "medical_conditions": [
                {"id": 3, "details": "Asthma", "severity": "mild", "notes": "Inhaler on site"}
            ],
            "accessibility_requirements": [
                {"id": 2, "details": "Wheelchair", "notes": "Accessible parking requested"}
            ],
            "emergency_contact": {
                "first_name": "Jane",
                "last_name": "Doe",
                "relationship": "parent",
                "phone_number": "+44 1234 567890"
            }
        }
    """
    dietary_requirements = PersonalInfoItemSerializer(
        many=True,
        required=False,
        help_text="Dietary restrictions and requirements"
    )
    medical_conditions = MedicalConditionItemSerializer(
        many=True,
        required=False,
        help_text="Medical conditions and allergies"
    )
    accessibility_requirements = PersonalInfoItemSerializer(
        many=True,
        required=False,
        help_text="Accessibility needs and accommodations"
    )
    emergency_contact = EmergencyContactDraftSerializer(
        required=False,
        help_text="Emergency contact (REQUIRED for attendees under 18)"
    )


# ============================================================================
# CONSENT & QUESTION SERIALIZERS
# ============================================================================

class AttendeeConsentDraftSerializer(serializers.Serializer):
    """
    Consent record indicating whether attendee consents to something.
    
    The 'consent_id' references a Consent record in the database.
    'consent_given' must be True for all required consents.
    
    Example:
        {
            "consent_id": 5,
            "consent_given": true
        }
    """
    consent_id = serializers.IntegerField(
        help_text="ID of the Consent record"
    )
    consent_given = serializers.BooleanField(
        default=False,
        help_text="Whether attendee gave consent (must be True for required consents)"
    )


class EventQuestionAnswerDraftSerializer(serializers.Serializer):
    """
    Answer to an event question with support for multiple formats.
    
    Supports:
    - Text answers (free-form text)
    - Multiple choice (selected_option_ids)
    - File uploads (upload_resource_id or upload_url)
    - Numeric answers (answer_text with numeric value)
    
    Validation ensures at least one answer format is provided.
    
    Examples:
        {
            "question_id": "550e8400-e29b-41d4-a716-446655440000",
            "answer_text": "Yes, I am available"
        }
        
        {
            "question_id": "550e8400-e29b-41d4-a716-446655440001",
            "selected_option_ids": [1, 3]
        }
        
        {
            "question_id": "550e8400-e29b-41d4-a716-446655440002",
            "upload_resource_id": 42
        }
    """
    question_id = serializers.UUIDField(
        help_text="UUID of the EventQuestion"
    )
    answer_text = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Text answer (for text/numeric questions)"
    )
    selected_option_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="IDs of selected options (for choice questions)"
    )
    upload_resource_id = serializers.IntegerField(
        required=False,
        help_text="ID of uploaded Resource (for file questions)"
    )
    upload_url = serializers.URLField(
        required=False,
        help_text="URL of uploaded file (alternative to upload_resource_id)"
    )

    def validate(self, attrs):
        answer_text = attrs.get('answer_text')
        selected_option_ids = attrs.get('selected_option_ids', [])
        upload_resource_id = attrs.get('upload_resource_id')
        upload_url = attrs.get('upload_url')

        if upload_resource_id and upload_url:
            raise serializers.ValidationError(
                'Provide only one of upload_resource_id or upload_url.'
            )

        if not answer_text and not selected_option_ids and not upload_resource_id and not upload_url:
            raise serializers.ValidationError(
                'An answer, selected options, or upload reference is required.'
            )

        return attrs


# ============================================================================
# ATTENDEE CHECKOUT SERIALIZERS
# ============================================================================

class AttendeeDraftSerializer(serializers.Serializer):
    """
    Complete attendee draft data for creation during checkout.
    
    Creates a new Attendee record with full personal information.
    Validates all nested personal info, consents, and event responses.
    
    Key fields:
    - attendee_id: UUID of existing attendee (use this OR attendee_draft, not both)
    - personal_info: Medical, dietary, accessibility, emergency contact
    - consents: Event consent records
    - question_answers: Event question responses
    
    Example:
        {
            "first_name": "John",
            "last_name": "Smith",
            "email": "john@example.com",
            "phone_number": "+44 7123 456789",
            "date_of_birth": "1990-05-15",
            "gender": "male",
            "relationship_to_user": "self",
            "area_from": 1,
            "personal_info": {...},
            "consents": [...],
            "question_answers": [...]
        }
    """
    first_name = serializers.CharField(
        max_length=150,
        help_text="First name of attendee"
    )
    last_name = serializers.CharField(
        max_length=150,
        help_text="Last name of attendee"
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Email address (optional, for contact purposes)"
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=20,
        help_text="Phone number (optional, international format supported)"
    )
    date_of_birth = serializers.DateField(
        help_text="Date of birth (YYYY-MM-DD) - used for age validation and pricing"
    )
    gender = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Gender (free-form text for inclusivity)"
    )
    relationship_to_user = serializers.ChoiceField(
        choices=['self', 'spouse', 'child', 'friend', 'parent', 'sibling', 'other'],
        help_text="Relationship to the user making the booking"
    )
    area_from = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional ID of AreaLocation (active areas only)"
    )
    personal_info = AttendeePersonalInfoDraftSerializer(
        required=False,
        help_text="Personal information (medical, dietary, accessibility, emergency contact)"
    )
    consents = AttendeeConsentDraftSerializer(
        many=True,
        required=False,
        help_text="Consent records (required consents must be True)"
    )
    question_answers = EventQuestionAnswerDraftSerializer(
        many=True,
        required=False,
        help_text="Event question responses (required questions must have answers)"
    )

    def validate_area_from(self, value):
        """Ensure area_from points to an active AreaLocation."""
        if value in (None, ''):
            return None

        from apps.locations.models import AreaLocation

        try:
            area = AreaLocation.objects.get(id=value, active=True)
        except AreaLocation.DoesNotExist:
            raise serializers.ValidationError(
                f'AreaLocation with id {value} does not exist or is not active.'
            )

        return area.id


class AttendeeCheckoutSerializer(serializers.Serializer):
    """
    Attendee selection for a specific checkout transaction.
    
    Each attendee selection includes:
    - Either an existing attendee_id OR attendee draft data (not both)
    - A booking package selection
    - Optional product variant selections
    
    Example:
        {
            "attendee_id": "550e8400-e29b-41d4-a716-446655440000",
            "package_id": 5,
            "product_selections": [
                {
                    "package_product_id": 1,
                    "variant_id": "550e8400-e29b-41d4-a716-446655440001",
                    "quantity": 2
                }
            ]
        }
    
    Or with attendee draft:
        {
            "attendee": {...AttendeeDraftSerializer...},
            "package_id": 5,
            "product_selections": [...]
        }
    """

    attendee_id = serializers.UUIDField(
        required=False,
        help_text="UUID of an existing attendee (use this OR attendee, not both)"
    )
    attendee = AttendeeDraftSerializer(
        required=False,
        help_text="Draft attendee data to create during checkout (use this OR attendee_id, not both)"
    )
    package_id = serializers.IntegerField(
        help_text="ID of the BookingPackage selected for this attendee"
    )
    product_selections = ProductSelectionSerializer(
        many=True,
        required=False,
        help_text="Optional product variant selections for package products"
    )

    def validate(self, attrs):
        """Validate attendee and package compatibility."""
        from apps.attendee.models import Attendee
        from apps.bookings.models import BookingPackage

        attendee_id = attrs.get('attendee_id')
        attendee_draft = attrs.get('attendee')
        package_id = attrs.get('package_id')
        product_selections = attrs.get('product_selections', [])

        # Exactly one of attendee_id or attendee_draft must be provided
        if bool(attendee_id) == bool(attendee_draft):
            raise serializers.ValidationError({
                'attendee_id': 'Provide either attendee_id or attendee, but not both.'
            })

        # Validate BookingPackage exists
        try:
            package = BookingPackage.objects.get(id=package_id)
        except BookingPackage.DoesNotExist:
            raise serializers.ValidationError({
                'package_id': f'BookingPackage with id {package_id} does not exist.'
            })

        if attendee_id:
            try:
                attendee = Attendee.objects.get(attendee_id=attendee_id)
            except Attendee.DoesNotExist:
                raise serializers.ValidationError({
                    'attendee_id': f'Attendee with id {attendee_id} does not exist.'
                })

            if package.event_id != attendee.event_id:
                raise serializers.ValidationError({
                    'package_id': 'Package must belong to the same event as the attendee.'
                })

            attrs['_attendee'] = attendee
        else:
            attrs['_attendee_draft'] = attendee_draft

        # Validate product selections match package products
        if product_selections:
            selected_product_ids = [ps['package_product_id'] for ps in product_selections]
            if len(selected_product_ids) != len(set(selected_product_ids)):
                raise serializers.ValidationError({
                    'product_selections': 'Duplicate package_product_id entries are not allowed.'
                })

            package_product_ids = set(ps['package_product_id'] for ps in product_selections)
            actual_package_products = package.package_products.values_list('id', flat=True)

            invalid_ids = package_product_ids - set(actual_package_products)
            if invalid_ids:
                raise serializers.ValidationError({
                    'product_selections': f'PackageProduct IDs {invalid_ids} do not belong to package {package.name}'
                })

        attrs['_package'] = package
        return attrs


# ============================================================================
# CHECKOUT SERIALIZERS
# ============================================================================

class CheckoutSerializer(serializers.Serializer):
    """
    Main checkout serializer for creating bookings with payments.
    
    **Two-phase flow:**
    1. **Validation phase**: Validates intent, payment method, attendees
    2. **Processing phase**: (handled by viewset) Creates payment or finalizes booking
    
    **Important notes:**
    - All prices are calculated server-side; frontend must not send prices
    - Booking & attendees created on checkout submission (not after payment)
    - Payment status tracked via Payment model
    - Stripe payments auto-create tickets; bank transfers await manual approval
    
    **Request flow:**
    1. Frontend submits checkout with valid intent, payment method, attendees
    2. Serializer validates all data (throws ValidationError if invalid)
    3. Viewset creates Payment model with metadata
    4. For Stripe: payment already confirmed, so finalize immediately
    5. For bank transfer: return reference, await manual admin approval
    
    **Example request:**
        {
            "booking_intent_id": "550e8400-e29b-41d4-a716-446655440000",
            "payment_method_id": 1,
            "stripe_payment_intent_id": "pi_1234567890abcdef" (optional),
            "attendees": [
                {
                    "attendee_id": "550e8400-e29b-41d4-a716-446655440001",
                    "package_id": 5,
                    "product_selections": []
                }
            ]
        }
    
    **Example response (Stripe, payment confirmed):**
        {
            "booking_id": 123,
            "booking_reference": "BKG-ABC-2025",
            "payment_id": "550e8400-e29b-41d4-a716-446655440002",
            "payment_reference": "PAY-XYZ-2025",
            "total_amount": "150.00",
            "currency": "GBP",
            "status": "confirmed",
            "message": "Booking confirmed and tickets created",
            "tickets": [
                {
                    "ticket_id": "550e8400-e29b-41d4-a716-446655440003",
                    "ticket_code": "TC-ABC-001",
                    "attendee_name": "John Smith",
                    "_links": {"self": "..."}
                }
            ],
            "_links": {"self": "...", "attendees": "...", "tickets": "..."}
        }
    
    **Example response (Bank transfer, awaiting payment verification):**
        {
            "booking_id": 124,
            "booking_reference": "BKG-DEF-2025",
            "payment_id": "550e8400-e29b-41d4-a716-446655440004",
            "payment_reference": "PAY-UVW-2025",
            "total_amount": "200.00",
            "currency": "GBP",
            "status": "pending_payment",
            "message": "Booking created. Complete bank transfer to finalize.",
            "bank_transfer_reference": "BT-XYZ-2025",
            "bank_transfer_instructions": "Transfer £200.00 to our account...",
            "tickets": [],
            "_links": {"self": "...", "attendees": "...", "tickets": "..."}
        }
    """
    
    booking_intent_id = serializers.UUIDField(
        help_text="UUID of the BookingIntent to complete"
    )
    payment_method_id = serializers.IntegerField(
        required=True,
        help_text="Payment method ID for checkout."
    )
    payment_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional draft payment ID reserved before checkout for bank transfer flows"
    )
    stripe_payment_intent_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Stripe PaymentIntent ID when payment is already confirmed (Stripe only)"
    )
    bank_transfer_evidence_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Pre-uploaded bank transfer evidence ID bound to this booking intent"
    )
    attendees = AttendeeCheckoutSerializer(
        many=True,
        help_text="List of attendee selections with packages and products"
    )

    def validate_booking_intent_id(self, value):
        """Validate booking intent exists and is active."""
        try:
            intent = BookingIntent.objects.get(booking_intent_id=value)
        except BookingIntent.DoesNotExist:
            raise serializers.ValidationError(
                f'BookingIntent with id {value} does not exist.'
            )
        
        if not intent.is_active:
            raise serializers.ValidationError(
                f'BookingIntent {value} is not active. Status: {intent.get_status_display()}, '
                f'Expired: {intent.is_expired}'
            )
        
        if not intent.can_create_booking():
            raise serializers.ValidationError(
                f'Cannot create booking from intent {value}. Event may be full or closed.'
            )
        
        return value
    
    def validate_payment_method_id(self, value):
        """Validate payment method exists and is active."""
        # Support legacy/free-checkout placeholders from clients.
        if value in (None, 0) or value < 0:
            return None

        from apps.payments.models import PaymentMethod
        
        try:
            method = PaymentMethod.objects.get(id=value)
        except PaymentMethod.DoesNotExist:
            raise serializers.ValidationError(
                f'PaymentMethod with id {value} does not exist.'
            )
        
        if not method.is_active:
            raise serializers.ValidationError(
                f'PaymentMethod {method.title} is not currently active.'
            )
        
        return value
    
    def validate(self, attrs):
        """
        Comprehensive cross-field validation.
        
        Uses CheckoutValidationService to validate:
        - Intent and method compatibility
        - Attendee count
        - All attendee data
        - Questions, consents, personal info
        """
        from apps.bookings.services.checkout_validation import CheckoutValidationService
        from apps.payments.models import PaymentMethodTypeChoices
        
        intent_id = attrs.get('booking_intent_id')
        method_id = attrs.get('payment_method_id')
        payment_id = attrs.get('payment_id')
        attendee_selections = attrs.get('attendees', [])
        stripe_payment_intent_id = attrs.get('stripe_payment_intent_id')
        bank_transfer_evidence_id = attrs.get('bank_transfer_evidence_id')
        
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        
        # Validate using CheckoutValidationService
        intent, method = CheckoutValidationService.validate_checkout_request(
            intent_id,
            method_id,
            attendee_selections,
            user
        )
        
        # Store validated objects for processing
        attrs['_intent'] = intent
        attrs['_payment_method'] = method

        payment_obj = None
        if payment_id:
            from apps.payments.models import Payment

            try:
                payment_obj = Payment.objects.select_related('method', 'event', 'user').get(payment_id=payment_id)
            except Payment.DoesNotExist:
                raise serializers.ValidationError({
                    'payment_id': 'Reserved payment was not found.'
                })

            if payment_obj.user_id != getattr(user, 'id', None):
                raise serializers.ValidationError({
                    'payment_id': 'Reserved payment does not belong to the authenticated user.'
                })

            if payment_obj.event_id != intent.event_id:
                raise serializers.ValidationError({
                    'payment_id': 'Reserved payment does not belong to this event.'
                })

            if payment_obj.method_id and method and payment_obj.method_id != method.id:
                raise serializers.ValidationError({
                    'payment_id': 'Reserved payment does not match the selected payment method.'
                })

            if payment_obj.status not in {'DRAFTING', 'PENDING'}:
                raise serializers.ValidationError({
                    'payment_id': 'Reserved payment can no longer be used for checkout.'
                })

            payment_metadata = payment_obj.metadata or {}
            if str(payment_metadata.get('checkout_intent_id') or '') != str(intent.booking_intent_id):
                raise serializers.ValidationError({
                    'payment_id': 'Reserved payment does not belong to this booking intent.'
                })

            attrs['_payment_obj'] = payment_obj

        if method and method.method_type != PaymentMethodTypeChoices.BANK_TRANSFER and bank_transfer_evidence_id:
            raise serializers.ValidationError({
                'bank_transfer_evidence_id': 'bank_transfer_evidence_id is only valid when payment method is BANK_TRANSFER.'
            })

        if (
            method
            and method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER
            and method.bank_transfer_required_immediately
            and not bank_transfer_evidence_id
        ):
            raise serializers.ValidationError({
                'bank_transfer_evidence': (
                    'Bank transfer evidence is required immediately for this payment method. '
                    'Upload evidence first, then provide bank_transfer_evidence_id during checkout.'
                )
            })

        evidence_obj = None
        if method and method.method_type == PaymentMethodTypeChoices.BANK_TRANSFER and bank_transfer_evidence_id:
            try:
                evidence_obj = BankTransferEvidence.objects.select_related('payment').get(bank_transfer_id=bank_transfer_evidence_id)
            except BankTransferEvidence.DoesNotExist:
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Uploaded bank transfer evidence was not found.'
                })

            if evidence_obj.payment_id:
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'This evidence has already been consumed by a payment.'
                })

            metadata = evidence_obj.metadata or {}
            if str(metadata.get('booking_intent_id') or '') != str(intent.booking_intent_id):
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Evidence does not belong to this booking intent.'
                })

            if int(metadata.get('uploaded_by_user_id') or 0) != int(getattr(user, 'id', 0) or 0):
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Evidence does not belong to the authenticated user.'
                })

            if not evidence_obj.evidence_file:
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Evidence file is missing for this upload.'
                })
            if not evidence_obj.payer_name:
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Payer name is missing for this upload.'
                })
            if not evidence_obj.payer_account_last4:
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Payer account last 4 is missing for this upload.'
                })
            if not evidence_obj.amount_on_evidence or evidence_obj.amount_on_evidence.amount <= 0:
                raise serializers.ValidationError({
                    'bank_transfer_evidence_id': 'Evidence amount must be greater than zero.'
                })

            attrs['_bank_transfer_evidence_obj'] = evidence_obj

        if stripe_payment_intent_id:
            attrs['_stripe_payment_intent_id'] = stripe_payment_intent_id
        
        return attrs


class CheckoutPreviewSerializer(serializers.Serializer):
    """
    Read-only checkout preview serializer (safe for calculations without persistence).
    
    Similar to CheckoutSerializer but:
    - Does not require payment method
    - Does not create any database records
    - Used only to calculate totals and preview what would happen
    
    Response includes calculated totals but NO booking/attendee creation.
    
    **Example request:**
        {
            "booking_intent_id": "550e8400-e29b-41d4-a716-446655440000",
            "attendees": [
                {
                    "attendee": {...AttendeeDraftSerializer...},
                    "package_id": 5
                }
            ]
        }
    
    **Example response:**
        {
            "total_amount": "150.00",
            "currency": "GBP",
            "attendees": [
                {
                    "name": "John Smith",
                    "package_name": "Standard Package",
                    "package_price": "150.00",
                    "products": [
                        {
                            "product_name": "Merchandise",
                            "variant_name": "Large",
                            "quantity": 1,
                            "price": "25.00"
                        }
                    ],
                    "total": "175.00"
                }
            ]
        }
    """

    booking_intent_id = serializers.UUIDField(
        help_text="UUID of the BookingIntent to preview"
    )
    attendees = AttendeeCheckoutSerializer(
        many=True,
        help_text="List of attendee selections with packages and products"
    )

    def validate_booking_intent_id(self, value):
        """Validate booking intent exists and is active."""
        try:
            intent = BookingIntent.objects.get(booking_intent_id=value)
        except BookingIntent.DoesNotExist:
            raise serializers.ValidationError(
                f'BookingIntent with id {value} does not exist.'
            )

        if not intent.is_active:
            raise serializers.ValidationError(
                f'BookingIntent {value} is not active (expired: {intent.is_expired})'
            )

        return value

    def validate(self, attrs):
        """Validate preview request (lighter validation than checkout)."""
        intent_id = attrs.get('booking_intent_id')
        attendee_selections = attrs.get('attendees', [])

        intent = BookingIntent.objects.get(booking_intent_id=intent_id)

        # Validate attendee count matches
        if len(attendee_selections) != intent.intended_ticket_count:
            raise serializers.ValidationError({
                'attendees': (
                    f'Expected {intent.intended_ticket_count} attendees, '
                    f'received {len(attendee_selections)}'
                )
            })

        attrs['_intent'] = intent
        return attrs
