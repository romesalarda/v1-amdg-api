"""
Discount Checkout Integration Tests

Tests discount code validation endpoint and discount application at checkout/preview:
- validate-code endpoint (valid, invalid, inactive, wrong event)
- Checkout preview with code: correct price reduction and breakdown
- Checkout preview without code: existing discounts (age-based, etc.) still apply
- Checkout with code: payment metadata contains frozen discount snapshot
- Attendee not matching rules: no discount applied
- No-code checkout: regression (existing flow unchanged)
- code_matches null-safety: None code does not match a CODE_MATCHES rule
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from djmoney.money import Money
from rest_framework import status
from rest_framework.test import APIClient

from apps.attendee.models import Attendee, AttendeeRelationship
from apps.bookings.models import (
    Booking, BookingIntent, BookingPackage,
    TicketType, TicketScopeChoices,
)
from apps.common.models.availability import AvailabilityWindow, AvailabilityTypeChoices
from apps.events.models import (
    Event, EventType, EventStatusChoices,
    EventAuthorization, EventAuthorizationStatusChoices,
)
from apps.locations.models import (
    AreaLocation, ChapterLocation, ClusterLocation, CountryLocation,
    GeneralSectorType, SpecificSectorType,
)
from apps.organisations.models import Organisation
from apps.payments.models import (
    Discount, DiscountRule, DiscountRuleTypeChoices, DiscountType,
    Payment, PaymentMethod, PaymentMethodTypeChoices, PaymentStatusChoices,
)
from django.contrib.auth import get_user_model

User = get_user_model()


class DiscountCheckoutTestCase(TestCase):
    """Base test case with shared fixtures for discount checkout tests."""

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='discountuser',
            email='discountuser@example.com',
            password='testpass123',
        )
        self.client.force_authenticate(user=self.user)

        self.admin_user = User.objects.create_user(
            username='discountadmin',
            email='discountadmin@example.com',
            password='admin123',
            is_staff=True,
        )

        self.event_type = EventType.objects.create(
            title='DiscountConf',
            code='DC',
            created_by=self.user,
        )

        self.organisation = Organisation.objects.create(
            title='Discount Org',
            created_by=self.user,
        )

        self.event = Event.objects.create(
            title='Discount Test Event',
            display_code='DTE26',
            display_identifier='DTE26CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=30),
            end_datetime=timezone.now() + timedelta(days=32),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )

        AvailabilityWindow.objects.create(
            name='Registration Window',
            availability_type=AvailabilityTypeChoices.REGISTRATION,
            target_type=ContentType.objects.get_for_model(Event),
            target_id=self.event.id,
            available_from=timezone.now() - timedelta(days=1),
            available_to=timezone.now() + timedelta(days=60),
        )

        EventAuthorization.objects.create(
            event=self.event,
            status=EventAuthorizationStatusChoices.APPROVED,
            reviewed_by=self.admin_user,
        )

        self.country = CountryLocation.objects.create(
            country='GB',
            general_sector=GeneralSectorType.EUROPE,
            specific_sector=SpecificSectorType.WEST_EUROPE,
            active=True,
        )
        self.cluster = ClusterLocation.objects.create(
            cluster_name='Test Cluster',
            country=self.country,
            active=True,
        )
        self.chapter = ChapterLocation.objects.create(
            chapter_name='Test Chapter',
            cluster=self.cluster,
            active=True,
        )
        self.area = AreaLocation.objects.create(
            area_name='Test Area',
            chapter=self.chapter,
            active=True,
        )

        self.ticket_type = TicketType.objects.create(
            event=self.event,
            code='STD',
            title='Standard',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=self.event.end_datetime,
            created_by=self.user,
        )

        self.package = BookingPackage.objects.create(
            name='Standard Package',
            event=self.event,
            ticket_type=self.ticket_type,
            base_amount=Money(100, 'GBP'),
            created_by=self.user,
        )

        self.payment_method = PaymentMethod.objects.create(
            event=self.event,
            method_type=PaymentMethodTypeChoices.BANK_TRANSFER,
            title='Bank Transfer',
            is_active=True,
            created_by=self.user,
        )

    def _create_code_discount(self, code, amount=None, percentage=None, active=True):
        """Helper: create a Discount with a CODE_MATCHES rule."""
        discount_type = DiscountType.FIXED if amount is not None else DiscountType.PERCENTAGE
        discount = Discount.objects.create(
            name=f'Code Discount ({code})',
            discount_type=discount_type,
            amount=Money(amount, 'GBP') if amount is not None else None,
            percentage=Decimal(str(percentage)) if percentage is not None else None,
            active=active,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            name=f'Code rule ({code})',
            discount=discount,
            value=code,
            active=True,
        )
        return discount

    def _create_booking_intent(self, ticket_count=1):
        return BookingIntent.objects.create(
            event=self.event,
            intended_ticket_count=ticket_count,
            made_by=self.user,
        )

    def _create_attendee_in_booking(self):
        booking = Booking.objects.create(
            event=self.event,
            made_by=self.user,
        )
        attendee = Attendee.objects.create(
            first_name='Test',
            last_name='Attendee',
            email='attendee@discount.com',
            date_of_birth=date(1995, 6, 15),
            event=self.event,
            user=self.user,
            booking=booking,
            relationship_to_user=AttendeeRelationship.SELF,
            area_from=self.area,
            defined_by=self.user,
        )
        return booking, attendee


# ---------------------------------------------------------------------------
# 1. validate-code endpoint
# ---------------------------------------------------------------------------

class ValidateCodeEndpointTests(DiscountCheckoutTestCase):

    def test_validate_code_valid_code_returns_true(self):
        """Active CODE_MATCHES discount for the correct event returns valid=true."""
        self._create_code_discount(code='EARLYBIRD', amount=10)

        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'code': 'EARLYBIRD', 'event_id': self.event.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['valid'])

    def test_validate_code_invalid_code_returns_false(self):
        """Non-existent code returns valid=false."""
        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'code': 'DOESNOTEXIST', 'event_id': self.event.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['valid'])

    def test_validate_code_inactive_discount_returns_false(self):
        """Code whose parent Discount is inactive returns valid=false."""
        self._create_code_discount(code='INACTIVECODE', amount=5, active=False)

        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'code': 'INACTIVECODE', 'event_id': self.event.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['valid'])

    def test_validate_code_wrong_event_returns_false(self):
        """Code that exists but belongs to a different event's package returns valid=false."""
        # Create another event and package
        other_event = Event.objects.create(
            title='Other Event',
            display_code='OE26',
            display_identifier='OE26CONF001',
            created_by=self.user,
            event_type=self.event_type,
            start_datetime=timezone.now() + timedelta(days=60),
            end_datetime=timezone.now() + timedelta(days=62),
            status=EventStatusChoices.OPEN,
            organisation=self.organisation,
        )
        other_ticket_type = TicketType.objects.create(
            event=other_event,
            code='OTH',
            title='Standard',
            scope=TicketScopeChoices.FULL_EVENT,
            valid_from=timezone.now(),
            valid_until=other_event.end_datetime,
            created_by=self.user,
        )
        other_package = BookingPackage.objects.create(
            name='Other Package',
            event=other_event,
            ticket_type=other_ticket_type,
            base_amount=Money(80, 'GBP'),
            created_by=self.user,
        )
        # Create discount on the OTHER package
        other_discount = Discount.objects.create(
            name='Other event code',
            discount_type=DiscountType.FIXED,
            amount=Money(10, 'GBP'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=other_package.id,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.CODE_MATCHES,
            name='Other event code rule',
            discount=other_discount,
            value='OTHEREVENT',
            active=True,
        )

        # Validating against self.event should return false
        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'code': 'OTHEREVENT', 'event_id': self.event.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['valid'])

    def test_validate_code_requires_authentication(self):
        """validate-code requires authenticated user."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'code': 'EARLYBIRD', 'event_id': self.event.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_validate_code_missing_code_returns_400(self):
        """Missing code field returns 400."""
        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'event_id': self.event.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validate_code_missing_event_id_returns_400(self):
        """Missing event_id field returns 400."""
        response = self.client.post(
            '/api/payments/discounts/validate-code/',
            {'code': 'EARLYBIRD'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# 2. Checkout preview with discount_code
# ---------------------------------------------------------------------------

class CheckoutPreviewWithDiscountCodeTests(DiscountCheckoutTestCase):

    def test_preview_with_valid_code_returns_reduced_total(self):
        """Preview with a valid CODE_MATCHES discount reduces the total correctly."""
        self._create_code_discount(code='SAVE10', amount=10)
        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'discount_code': 'SAVE10',
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Base is £100, discount is £10 → total £90
        self.assertEqual(response.data['total_amount'], '90.00')
        self.assertEqual(response.data['discount_code_applied'], 'SAVE10')

        pkg = response.data['attendees'][0]['package']
        self.assertEqual(pkg['base_amount'], '100.00')
        self.assertEqual(pkg['discount_total'], '10.00')
        self.assertEqual(pkg['final_amount'], '90.00')
        self.assertEqual(len(pkg['applied_discounts']), 1)
        self.assertEqual(pkg['applied_discounts'][0]['name'], 'Code Discount (SAVE10)')

    def test_preview_with_percentage_code_discount(self):
        """Preview with a percentage CODE_MATCHES discount applies correct % reduction."""
        self._create_code_discount(code='PCT20', percentage=20)
        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'discount_code': 'PCT20',
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Base £100, 20% off → £80
        self.assertEqual(response.data['total_amount'], '80.00')

    def test_preview_without_code_no_code_discount_applied(self):
        """Preview without code does not apply CODE_MATCHES discount (null-safety)."""
        self._create_code_discount(code='SECRETCODE', amount=50)
        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # No code → no discount → full £100
        self.assertEqual(response.data['total_amount'], '100.00')
        pkg = response.data['attendees'][0]['package']
        self.assertEqual(pkg['discount_total'], '0.00')
        self.assertEqual(len(pkg['applied_discounts']), 0)

    def test_preview_with_wrong_code_no_discount(self):
        """Preview with a non-matching code returns full price with no applied discounts."""
        self._create_code_discount(code='REALCODE', amount=20)
        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'discount_code': 'WRONGCODE',
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_amount'], '100.00')
        pkg = response.data['attendees'][0]['package']
        self.assertEqual(pkg['discount_total'], '0.00')

    def test_preview_code_and_age_rule_both_apply(self):
        """Code discount stacks with automatic age-based discount when both rules pass."""
        # Age-based discount: 10% off for adults (age > 18)
        age_discount = Discount.objects.create(
            name='Adult Discount',
            discount_type=DiscountType.PERCENTAGE,
            percentage=Decimal('10.00'),
            active=True,
            target_type=ContentType.objects.get_for_model(BookingPackage),
            target_id=self.package.id,
        )
        DiscountRule.objects.create(
            rule_type=DiscountRuleTypeChoices.IS_AGE_GT,
            name='Adult rule',
            discount=age_discount,
            value='18',
            active=True,
        )
        # Code discount: £5 off
        self._create_code_discount(code='EXTRA5', amount=5)

        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()
        # Attendee DOB: 1995-06-15 → age ~30, qualifies for age discount

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'discount_code': 'EXTRA5',
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Base £100, 10% → £10 + £5 fixed = £15 total discount → £85
        self.assertEqual(response.data['total_amount'], '85.00')
        pkg = response.data['attendees'][0]['package']
        self.assertEqual(len(pkg['applied_discounts']), 2)

    def test_preview_discount_code_applied_field_echoed(self):
        """Response echoes the discount_code_applied field."""
        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'discount_code': 'ANYCODE',
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['discount_code_applied'], 'ANYCODE')

    def test_preview_no_code_discount_code_applied_is_none(self):
        """Without a code, discount_code_applied is None in response."""
        intent = self._create_booking_intent()
        _, attendee = self._create_attendee_in_booking()

        response = self.client.post(
            '/api/bookings/list/checkout-preview/',
            {
                'booking_intent_id': str(intent.booking_intent_id),
                'attendees': [
                    {'attendee_id': str(attendee.attendee_id), 'package_id': self.package.id}
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['discount_code_applied'])


# ---------------------------------------------------------------------------
# 3. Checkout with discount_code → payment metadata snapshot
# ---------------------------------------------------------------------------

class CheckoutWithDiscountCodeMetadataTests(DiscountCheckoutTestCase):

    def _checkout_with_code(self, code, attendee):
        """Helper: run a full checkout with the given code and return the payment."""
        intent = self._create_booking_intent()

        with patch('apps.bookings.services.checkout_finaliser.BookingCheckoutFinaliser.finalize_for_bank_transfer') as mock_finalize:
            mock_finalize.return_value = {'booking': None}
            with patch('apps.payments.models.payments.Payment.transition_to'):
                response = self.client.post(
                    '/api/bookings/list/checkout/',
                    {
                        'booking_intent_id': str(intent.booking_intent_id),
                        'payment_method_id': self.payment_method.id,
                        'discount_code': code,
                        'attendees': [
                            {
                                'attendee_id': str(attendee.attendee_id),
                                'package_id': self.package.id,
                            }
                        ],
                    },
                    format='json',
                )
        return response

    def test_checkout_metadata_contains_discount_code(self):
        """Payment metadata must contain the discount_code field."""
        self._create_code_discount(code='META10', amount=10)
        _, attendee = self._create_attendee_in_booking()

        response = self._checkout_with_code('META10', attendee)

        # Expect either 201 (created) or 200 (idempotent) - just not 4xx
        self.assertIn(response.status_code, [200, 201])

        payment = Payment.objects.filter(
            user=self.user,
            event=self.event,
        ).order_by('-id').first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.metadata.get('discount_code'), 'META10')

    def test_checkout_metadata_contains_applied_discounts_snapshot(self):
        """Payment metadata must contain an applied_discounts_snapshot list."""
        self._create_code_discount(code='SNAP15', amount=15)
        _, attendee = self._create_attendee_in_booking()

        response = self._checkout_with_code('SNAP15', attendee)

        self.assertIn(response.status_code, [200, 201])

        payment = Payment.objects.filter(
            user=self.user,
            event=self.event,
        ).order_by('-id').first()
        self.assertIsNotNone(payment)
        snapshot = payment.metadata.get('applied_discounts_snapshot')
        self.assertIsNotNone(snapshot)
        self.assertIsInstance(snapshot, list)
        self.assertEqual(len(snapshot), 1)

        entry = snapshot[0]
        self.assertEqual(entry['attendee_index'], 0)
        self.assertEqual(entry['package_id'], self.package.id)
        self.assertEqual(len(entry['discount_breakdown']), 1)
        self.assertEqual(entry['discount_breakdown'][0]['name'], 'Code Discount (SNAP15)')
        self.assertEqual(entry['total_discount'], '15.00')

    def test_checkout_without_code_metadata_has_no_discount(self):
        """Without a code, metadata discount fields are null/empty — regression."""
        self._create_code_discount(code='NOTUSED', amount=10)
        _, attendee = self._create_attendee_in_booking()

        response = self._checkout_with_code(None, attendee)

        self.assertIn(response.status_code, [200, 201])

        payment = Payment.objects.filter(
            user=self.user,
            event=self.event,
        ).order_by('-id').first()
        self.assertIsNotNone(payment)
        self.assertIsNone(payment.metadata.get('discount_code'))
        snapshot = payment.metadata.get('applied_discounts_snapshot', [])
        # No discounts should be applied
        for entry in snapshot:
            self.assertEqual(len(entry.get('discount_breakdown', [])), 0)


# ---------------------------------------------------------------------------
# 4. Evaluator null-safety
# ---------------------------------------------------------------------------

class DiscountEvaluatorNullSafetyTests(DiscountCheckoutTestCase):

    def test_none_code_does_not_match_code_rule(self):
        """Attendee.pricing_context() with no code must not match a CODE_MATCHES rule."""
        from apps.payments.services.evaluator import DiscountContext, DiscountRuleEvaluator
        from apps.payments.models.discounts import DiscountRule as DRule, DiscountRuleTypeChoices as DRT

        _, attendee = self._create_attendee_in_booking()
        context = attendee.pricing_context(code=None)

        # Build a fake rule object (not saved)
        import types
        rule = types.SimpleNamespace(rule_type=DRT.CODE_MATCHES, value='SECRET')

        evaluator = DiscountRuleEvaluator()
        result = evaluator.code_matches(rule, context)
        self.assertFalse(result)

    def test_matching_code_evaluates_true(self):
        """pricing_context with the correct code should match a CODE_MATCHES rule."""
        from apps.payments.services.evaluator import DiscountRuleEvaluator
        from apps.payments.models.discounts import DiscountRuleTypeChoices as DRT

        _, attendee = self._create_attendee_in_booking()
        context = attendee.pricing_context(code='SECRET')

        import types
        rule = types.SimpleNamespace(rule_type=DRT.CODE_MATCHES, value='SECRET')

        evaluator = DiscountRuleEvaluator()
        result = evaluator.code_matches(rule, context)
        self.assertTrue(result)

    def test_location_none_does_not_crash(self):
        """location_matches with None location in metadata returns False, not AttributeError."""
        from apps.payments.services.evaluator import DiscountContext, DiscountRuleEvaluator
        from apps.payments.models.discounts import DiscountRuleTypeChoices as DRT

        context = DiscountContext(
            user=None,
            event=None,
            metadata={'location': None},
        )
        import types
        rule = types.SimpleNamespace(rule_type=DRT.LOCATION_MATCHES, value='London')

        evaluator = DiscountRuleEvaluator()
        result = evaluator.location_matches(rule, context)
        self.assertFalse(result)
