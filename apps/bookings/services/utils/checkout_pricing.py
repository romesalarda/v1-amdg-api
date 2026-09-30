"""
Checkout pricing calculation and speculative validation.

Computes the total checkout amount and per-attendee discount breakdown without
persisting any pricing side effects. Attendee/eligibility validation runs inside
a rolled-back savepoint so stock and eligibility checks can reuse the same model
methods as real booking creation without leaving residue on failure.
"""
import typing
from decimal import Decimal

from django.db import transaction
from django.contrib.auth.models import User
from djmoney.money import Money
from rest_framework.exceptions import ValidationError

from apps.attendee.models import Attendee, AttendeeRelationship
from apps.bookings.models import BookingIntent
from apps.payments.models import DiscountType
from apps.payments.services.evaluator import discount_applies


class CheckoutPricingCalculator:
    """Calculates checkout totals and validates attendee/product eligibility."""

    @staticmethod
    def calculate_total_and_validate(
        intent: BookingIntent,
        selections: typing.List[typing.Dict[str, typing.Any]],
        user: User,
        code: typing.Optional[str] = None,
    ) -> typing.Tuple[Money, typing.List[typing.Dict[str, typing.Any]]]:
        """
        Calculate the total amount for the booking and validate attendee selections.

        Args:
            intent: The BookingIntent associated with the checkout.
            selections: List of attendee selections including packages and product selections.
            user: The user making the booking (used for draft attendee `self` linkage).
            code: Optional discount code to apply.

        Returns:
            total_amount: The total amount for the booking after discounts.
            applied_discounts_snapshot: A snapshot of applied discounts for each attendee.
        """
        total_amount = Money(0, 'GBP')
        applied_discounts_snapshot = []
        preview_savepoint = transaction.savepoint()

        try:
            for attendee_index, selection in enumerate(selections):
                package = selection['_package']
                product_selections = selection.get('product_selections', [])

                attendee = selection.get('_attendee')
                if not attendee:
                    draft = selection.get('_attendee_draft') or {}
                    relationship = draft.get('relationship_to_user')
                    attendee_user = user if relationship == AttendeeRelationship.SELF else None
                    attendee = Attendee.objects.create(
                        event=intent.event,
                        user=attendee_user,
                        defined_by=user,
                        first_name=draft.get('first_name'),
                        last_name=draft.get('last_name'),
                        email=draft.get('email') or None,
                        phone_number=draft.get('phone_number') or None,
                        date_of_birth=draft.get('date_of_birth'),
                        gender=draft.get('gender') or None,
                        relationship_to_user=relationship,
                        area_from_id=draft.get('area_from'),
                    )

                if not package.can_use_package(user, attendee):
                    raise ValidationError({
                        'package_id': (
                            f'Attendee {attendee.attendee_id} is not eligible for package {package.name}.'
                        )
                    })

                attendee_context = attendee.pricing_context(code=code)
                package_base = package.modified_amount

                # Collect discount breakdown for this attendee's package
                attendee_discount_breakdown = []
                percentage_total = Decimal('0.00')
                fixed_total = Money(0, package_base.currency)
                for d in package.discounts:
                    if not discount_applies(d, attendee_context):
                        continue
                    if d.discount_type == DiscountType.PERCENTAGE:
                        discount_amount = package_base * (d.percentage / Decimal('100'))
                        percentage_total += d.percentage
                        value = str(d.percentage)
                    else:
                        discount_amount = d.amount
                        fixed_total += d.amount
                        value = str(d.amount.amount)
                    attendee_discount_breakdown.append({
                        'discount_id': str(d.discount_id),
                        'name': d.name,
                        'discount_type': d.discount_type,
                        'value': value,
                        'amount': str(discount_amount.amount),
                        'currency': package_base.currency.code,
                    })

                package_price = package.total_amount_for_context(attendee_context)
                total_amount += package_price

                applied_discounts_snapshot.append({
                    'attendee_index': attendee_index,
                    'attendee_id': str(attendee.attendee_id),
                    'attendee_name': attendee.full_name,
                    'package_id': package.id,
                    'package_name': package.name,
                    'discount_breakdown': attendee_discount_breakdown,
                    'total_discount': str(
                        min(
                            package_base * (percentage_total / Decimal('100')) + fixed_total,
                            package_base,
                        ).amount.quantize(Decimal('0.01'))
                    ),
                })

                if product_selections:
                    for prod_selection in product_selections:
                        package_product = prod_selection['_package_product']
                        variant = prod_selection['_variant']
                        quantity = int(prod_selection['quantity'])

                        if package_product.booking_package_id != package.id:
                            raise ValidationError({
                                'product_selections': (
                                    f'Package product {package_product.id} does not belong to package {package.id}.'
                                )
                            })

                        if not variant.can_attendee_purchase(attendee):
                            raise ValidationError({
                                'product_selections': (
                                    f'Attendee {attendee.attendee_id} is not eligible for selected variant {variant.variant_id}.'
                                )
                            })

                        try:
                            variant.can_attendee_purchase_quantity(attendee, quantity, raise_exception=True)
                        except Exception as exc:
                            raise ValidationError({'product_selections': str(exc)})

                        line_total = package_product.total_amount_with_variant(
                            variant=variant,
                            context=attendee_context,
                        ) * quantity
                        total_amount += line_total
        finally:
            transaction.savepoint_rollback(preview_savepoint)

        return total_amount, applied_discounts_snapshot
