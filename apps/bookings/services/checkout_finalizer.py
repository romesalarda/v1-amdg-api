from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from djmoney.money import Money

from apps.attendee.models import Attendee, AttendeeRelationship, AttendeeStatus, AttendeeActionChoices
from apps.attendee.models.personal.accessibility import AttendeeAccessibilityRequirement
from apps.attendee.models.personal.consent import AttendeeConsent, Consent
from apps.attendee.models.personal.dietary import AttendeeDietaryRequirement
from apps.attendee.models.personal.emergency import EmergencyContact
from apps.attendee.models.personal.medical import AttendeeMedicalCondition
from apps.bookings.models import Booking, BookingIntent
from apps.bookings.models.products import PackageProduct
from apps.common.models import Resource
from apps.events.models import EventQuestionAnswer, EventQuestionAnswerChoice
from apps.payments.models import Payment, PaymentMethodTypeChoices, PaymentStatusChoices
from apps.products.models import Order, OrderStatusChoices
from apps.products.models.product import ProductVariant
from core.utils.display import generate_human_readable_id


logger = logging.getLogger(__name__)


class CheckoutFinalizationError(Exception):
    pass


class BookingCheckoutFinalizer:
    """Create booking artifacts from frozen checkout metadata after payment confirmation."""

    @classmethod
    def finalize_from_payment(cls, payment: Payment, actor=None) -> dict:
        method_type = payment.method.method_type if payment.method else None
        if method_type == PaymentMethodTypeChoices.STRIPE:
            return cls.finalize_for_stripe(payment, actor=actor)
        # For any non-Stripe method that is already COMPLETED (e.g. CASH), create tickets immediately.
        if payment.status == PaymentStatusChoices.COMPLETED:
            return cls.finalize_for_stripe(payment, actor=actor)
        return cls.finalize_for_bank_transfer(payment, actor=actor)

    @classmethod
    def finalize_for_stripe(cls, payment: Payment, actor=None) -> dict:
        return cls._finalize_internal(payment, actor=actor, create_tickets=True)

    @classmethod
    def finalize_for_bank_transfer(cls, payment: Payment, actor=None) -> dict:
        return cls._finalize_internal(payment, actor=actor, create_tickets=False)

    @classmethod
    def _finalize_internal(cls, payment: Payment, actor=None, create_tickets: bool = True) -> dict:
        with transaction.atomic():
            # Lock only the payment row; joined nullable relations can break FOR UPDATE on PostgreSQL.
            payment = Payment.objects.select_for_update().get(pk=payment.pk)

            metadata = payment.metadata or {}
            if metadata.get("booking_finalized") and payment.target:
                return {
                    "booking": payment.target,
                    "tickets_created": False,
                    "already_finalized": True,
                }

            checkout_intent_id = metadata.get("checkout_intent_id")
            checkout_attendees = metadata.get("checkout_attendees") or []
            if not checkout_intent_id or not isinstance(checkout_attendees, list) or not checkout_attendees:
                raise CheckoutFinalizationError("Missing checkout metadata for finalization")

            try:
                intent = BookingIntent.objects.select_for_update().get(booking_intent_id=checkout_intent_id)
            except BookingIntent.DoesNotExist as exc:
                raise CheckoutFinalizationError("Booking intent not found for payment finalization") from exc

            if intent.completed_booking:
                booking = intent.completed_booking
                if payment.target_id != str(booking.pk):
                    payment.target = booking
                metadata["booking_finalized"] = True
                metadata["booking_id"] = str(booking.pk)
                metadata["booking_reference"] = booking.booking_reference
                payment.metadata = metadata
                payment.save(update_fields=["target_type", "target_id", "metadata", "updated_at"])
                return {
                    "booking": booking,
                    "tickets_created": False,
                    "already_finalized": True,
                }

            booking_reference = generate_human_readable_id(50, "BKG", intent.event.display_code[:10])
            booking = Booking.objects.create(
                event=intent.event,
                booking_reference=booking_reference,
                made_by=payment.user,
            )

            attendee_selection_metadata = []
            total_amount = Money(0, "GBP")
            orders = []

            for selection in checkout_attendees:
                attendee = cls._resolve_or_create_attendee(selection, payment, intent, booking, actor)

                package_id = selection.get("package_id")
                if not package_id:
                    raise CheckoutFinalizationError("Package selection is missing package_id")

                package = intent.event.booking_packages.filter(id=package_id).first()
                if not package:
                    raise CheckoutFinalizationError(f"Package {package_id} not found for event")

                if not package.can_use_package(payment.user, attendee):
                    raise CheckoutFinalizationError(
                        f"Attendee {attendee.attendee_id} is not eligible for package {package.name}"
                    )

                attendee_context = attendee.pricing_context()
                package_price = package.total_amount_for_context(attendee_context)
                total_amount += package_price

                selection_metadata = {
                    "attendee_id": str(attendee.attendee_id),
                    "attendee_name": attendee.full_name,
                    "package_id": package.id,
                    "package_name": package.name,
                    "frozen_price": str(package_price.amount),
                    "currency": package_price.currency.code,
                }

                product_selections = selection.get("product_selections") or []
                if product_selections:
                    order = Order.objects.create(
                        customer=payment.user,
                        attendee=attendee,
                        booking_package=package,
                        status=OrderStatusChoices.DRAFT,
                        total_amount=Money(0, package_price.currency.code),
                        created_by=actor or payment.user,
                    )

                    product_lines = []
                    for product_selection in product_selections:
                        package_product_id = product_selection.get("package_product_id")
                        variant_uuid = product_selection.get("variant_id")
                        quantity = int(product_selection.get("quantity") or 0)

                        package_product = PackageProduct.objects.filter(id=package_product_id).first()
                        if not package_product:
                            raise CheckoutFinalizationError(f"PackageProduct {package_product_id} not found")
                        if package_product.booking_package_id != package.id:
                            raise CheckoutFinalizationError(
                                f"PackageProduct {package_product_id} does not belong to package {package.id}"
                            )

                        variant = ProductVariant.objects.filter(variant_id=variant_uuid).first()
                        if not variant:
                            raise CheckoutFinalizationError(f"ProductVariant {variant_uuid} not found")

                        if variant.product_id != package_product.product_id:
                            raise CheckoutFinalizationError("Selected variant does not belong to selected package product")

                        try:
                            order_item = order.add_package_order_item(
                                package_product=package_product,
                                product_variant=variant,
                                quantity=quantity,
                            )
                        except DjangoValidationError as exc:
                            raise CheckoutFinalizationError(str(exc)) from exc

                        product_lines.append(
                            {
                                "package_product_id": package_product.id,
                                "variant_id": str(variant.variant_id),
                                "product_id": str(variant.product.product_id),
                                "quantity": quantity,
                                "unit_final_amount": str(order_item.unit_price.amount),
                                "line_total": str(order_item.total_price.amount),
                                "currency": order_item.total_price.currency.code,
                            }
                        )

                    order.transition_to(OrderStatusChoices.PENDING)
                    order.payment = payment
                    order.save(update_fields=["payment"])
                    orders.append(order)

                    total_amount += order.total_amount
                    selection_metadata["order_id"] = str(order.order_id)
                    selection_metadata["order_total"] = str(order.total_amount.amount)
                    selection_metadata["product_lines"] = product_lines

                attendee_selection_metadata.append(selection_metadata)

                attendee.mark_registered()

            if payment.base_amount and payment.base_amount != total_amount:
                raise CheckoutFinalizationError(
                    f"Payment amount mismatch during finalization: expected {payment.base_amount}, computed {total_amount}"
                )

            intent.mark_completed(save=False)
            intent.completed_booking = booking
            intent.save(update_fields=["status", "completed_booking"])

            metadata["booking_id"] = str(booking.pk)
            metadata["booking_reference"] = booking.booking_reference
            metadata["attendee_selections"] = attendee_selection_metadata
            metadata["booking_finalized"] = True
            payment.metadata = metadata
            payment.target = booking
            payment.save(update_fields=["target_type", "target_id", "metadata", "updated_at"])

            tickets_created = False
            if create_tickets and payment.status == PaymentStatusChoices.COMPLETED:
                from apps.bookings.services.ticket_creator import TicketCreatorService

                TicketCreatorService.create_tickets_for_payment(payment)
                booking.attendees.filter(status=AttendeeStatus.PENDING_PAYMENT).update(status=AttendeeStatus.REGISTERED)
                tickets_created = True

            logger.info(
                "Finalized payment %s into booking %s with %s order(s); tickets_created=%s",
                payment.payment_reference,
                booking.booking_reference,
                len(orders),
                tickets_created,
            )

            return {
                "booking": booking,
                "orders": orders,
                "tickets_created": tickets_created,
                "already_finalized": False,
            }

    @staticmethod
    def _resolve_or_create_attendee(selection: dict, payment: Payment, intent: BookingIntent, booking: Booking, actor=None) -> Attendee:
        attendee_uuid = selection.get("attendee_id")
        if attendee_uuid:
            attendee = Attendee.objects.filter(attendee_id=attendee_uuid, event=intent.event).first()
            if not attendee:
                raise CheckoutFinalizationError(f"Attendee {attendee_uuid} not found")
            attendee.booking = booking
            attendee.save(update_fields=["booking"])
            return attendee

        draft = selection.get("attendee_draft") or {}
        relationship = draft.get("relationship_to_user")
        attendee_user = payment.user if relationship == AttendeeRelationship.SELF else None

        attendee = Attendee.objects.create(
            event=intent.event,
            booking=booking,
            user=attendee_user,
            defined_by=actor or payment.user,
            first_name=draft.get("first_name"),
            last_name=draft.get("last_name"),
            email=draft.get("email") or None,
            phone_number=draft.get("phone_number") or None,
            date_of_birth=draft.get("date_of_birth"),
            gender=draft.get("gender") or None,
            relationship_to_user=relationship,
            area_from_id=draft.get("area_from"),
            status=AttendeeStatus.PENDING_PAYMENT,
        )

        personal_info = draft.get("personal_info") or {}

        for requirement in personal_info.get("dietary_requirements", []) or []:
            AttendeeDietaryRequirement.objects.create(
                attendee=attendee,
                dietary_requirement_id=requirement["id"],
                details=requirement.get("details"),
                notes=requirement.get("notes"),
                added_by=actor or payment.user,
            )

        for requirement in personal_info.get("accessibility_requirements", []) or []:
            AttendeeAccessibilityRequirement.objects.create(
                attendee=attendee,
                accessibility_requirement_id=requirement["id"],
                details=requirement.get("details"),
                notes=requirement.get("notes"),
                added_by=actor or payment.user,
            )

        for condition in personal_info.get("medical_conditions", []) or []:
            AttendeeMedicalCondition.objects.create(
                attendee=attendee,
                medical_condition_id=condition["id"],
                details=condition.get("details"),
                notes=condition.get("notes"),
                severity=condition.get("severity"),
                added_by=actor or payment.user,
            )

        emergency = personal_info.get("emergency_contact")
        if emergency:
            EmergencyContact.objects.create(
                attendee=attendee,
                first_name=emergency["first_name"],
                last_name=emergency["last_name"],
                relationship=emergency["relationship"],
                phone_number=emergency["phone_number"],
                email=emergency.get("email") or None,
                primary_contact=emergency.get("primary_contact", True),
                added_by=actor or payment.user,
            )

        consent_records = draft.get("consents", []) or []
        for consent_record in consent_records:
            consent_obj = Consent.objects.get(id=consent_record["consent_id"])
            consent_given = consent_record.get("consent_given", False)
            AttendeeConsent.objects.create(
                attendee=attendee,
                consent=consent_obj,
                consent_given=consent_given,
                given_at=timezone.now() if consent_given else None,
                given_by=(actor or payment.user) if consent_given else None,
                recorded_by=actor or payment.user,
            )

        question_answers = draft.get("question_answers", []) or []
        for answer in question_answers:
            answer_text = answer.get("answer_text") or ""
            upload_resource_id = answer.get("upload_resource_id")
            upload_url = answer.get("upload_url")

            if upload_resource_id:
                try:
                    answer_text = Resource.objects.get(id=upload_resource_id).resource_url
                except Resource.DoesNotExist:
                    answer_text = ""
            elif upload_url:
                answer_text = upload_url

            answer_obj = EventQuestionAnswer.objects.create(
                question_id=answer["question_id"],
                attendee=attendee,
                answer_text=answer_text,
            )

            selected_option_ids = answer.get("selected_option_ids", [])
            if selected_option_ids:
                EventQuestionAnswerChoice.objects.bulk_create(
                    [
                        EventQuestionAnswerChoice(answer=answer_obj, option_id=option_id)
                        for option_id in selected_option_ids
                    ]
                )

        return attendee
