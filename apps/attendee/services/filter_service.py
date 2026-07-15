"""
AttendeeFilterService

Applies structured filter bodies (from the POST /api/attendees/filter/ endpoint)
to an Attendee queryset. Each section maps directly to the validated data coming
from filter_serializers.py.

Logic is ported from AttendeeFilterSet so that the existing GET filterset is
unchanged, and the POST endpoint has a clean, independently tested code path.
"""
import math
from datetime import date

import typing    

from dateutil.relativedelta import relativedelta
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q, F, IntegerField, DateField, TimeField, Value, Case, When
from django.db.models.functions import Cast
from rest_framework.request import Request

from apps.attendee.models import (
    Attendee,
    AttendeeRelationship,
    AttendeeActionChoices,
)
from apps.attendee.models.checkin import CheckInAction, CheckInScanResult
from apps.events.models import EventFormQuestionTypeChoices, EventQuestionTypeChoices
from apps.products.models import OrderStatusChoices
from apps.payments.models import PaymentStatusChoices, PaymentMethodTypeChoices
from apps.common.models import VerificationStatus


# ── Payment-scoped helpers (mirrors FilterSet helpers) ────────────────────────

def _booking_payment_attendee_ids(payment_queryset: models.QuerySet) -> models.QuerySet:
    """
    Return attendee PKs whose booking is targeted by the supplied payments.
    Args:
        payment_queryset: A queryset of Payment objects, filtered to the relevant
            event and any other criteria (status, method, etc.)
    Returns:
        A queryset of Attendee PKs whose booking is targeted by the supplied payments.
    """
    from apps.bookings.models import Booking

    booking_ct = ContentType.objects.get_for_model(Booking)
    booking_ids = payment_queryset.filter(target_type=booking_ct).values_list('target_id', flat=True)
    return Attendee.objects.filter(booking_id__in=list(booking_ids)).values_list('id', flat=True)


def _filter_attendees_by_payment_queryset(queryset: models.QuerySet, payment_queryset: models.QuerySet, targets=None) -> models.QuerySet:
    '''
    Filter attendees by payment queryset across booking, order, and ticket payment paths.
    Args:
        queryset: A queryset of Attendee objects to filter.
        payment_queryset: A queryset of Payment objects, filtered to the relevant
            event and any other criteria (status, method, etc.)
        targets: An optional set of targets to filter by ('booking', 'order', 'ticket').
    Returns:
        A queryset of Attendee objects filtered by the payment queryset.
    '''
    selected_targets = set(targets or {'booking', 'order', 'ticket'})
    attendee_event_ids = queryset.values_list('event_id', flat=True).distinct()
    if attendee_event_ids.exists():
        payment_queryset = payment_queryset.filter(event_id__in=attendee_event_ids)

    criteria = Q()
    if 'ticket' in selected_targets:
        criteria |= Q(tickets__payment__in=payment_queryset)
    if 'order' in selected_targets:
        criteria |= Q(orders__payment__in=payment_queryset)
    if 'booking' in selected_targets:
        criteria |= Q(id__in=_booking_payment_attendee_ids(payment_queryset))

    if not criteria.children:
        return queryset.none()

    return queryset.filter(criteria).distinct()


def _filter_attendees_by_discount_queryset(queryset: models.QuerySet, discount_queryset: models.QuerySet) -> models.QuerySet:
    '''
    Filter attendees by discount queryset across booking packages and product variants.
    Args:
        queryset: A queryset of Attendee objects to filter.
        discount_queryset: A queryset of Discount objects, filtered to the relevant
            event and any other criteria (name, ID, etc.)
    Returns:
        A queryset of Attendee objects filtered by the discount queryset.
    '''
    from apps.bookings.models import BookingPackage
    from apps.products.models import ProductVariant

    booking_package_ct = ContentType.objects.get_for_model(BookingPackage)
    product_variant_ct = ContentType.objects.get_for_model(ProductVariant)

    booking_package_ids = discount_queryset.filter(target_type=booking_package_ct).values_list('target_id', flat=True)
    product_variant_ids = discount_queryset.filter(target_type=product_variant_ct).values_list('target_id', flat=True)

    criteria = (
        Q(tickets__package_id__in=booking_package_ids) |
        Q(orders__booking_package_id__in=booking_package_ids) |
        Q(orders__order_items__product_variant_id__in=product_variant_ids)
    )
    return queryset.filter(criteria).distinct()


# ── Main service ──────────────────────────────────────────────────────────────

class AttendeeFilterService:
    """
    Apply a validated filter body to an Attendee queryset.

    Instantiate with the request and the validated data from
    AttendeeFilterRequestSerializer, then call get_queryset().
    """

    def __init__(self, request: Request, validated_data: dict):
        '''
        Args:
            request: The Django request object, used for permission scoping.
            validated_data: The validated data from AttendeeFilterRequestSerializer.
        '''
        self.request = request
        self.data = validated_data
        self.filter_data = validated_data.get('filters') or {}

    # ── Base queryset ─────────────────────────────────────────────────────────

    def _base_queryset(self) -> models.QuerySet:
        '''
        Returns:
            A base queryset of Attendee objects for the specified event, with
            permission scoping applied based on the request user.
        '''
        user = self.request.user
        event_slug = self.data['event']

        qs = Attendee.objects.select_related(
            'event', 'user', 'area_from', 'booking', 'defined_by'
        ).prefetch_related(
            'emergency_contacts', 'organisations',
            'attendeedietaryrequirement__dietary_requirement',
            'attendeemedicalcondition__medical_condition',
            'attendeeaccessibilityrequirement__accessibility_requirement',
        ).filter(event__url_safe_title=event_slug)

        # Soft-delete: always exclude unless demographics.include_deleted is True
        demographics = self.filter_data.get('demographics') or {}
        if not demographics.get('include_deleted', False):
            qs = qs.filter(deleted_at__isnull=True)

        # Permission scoping
        if user.is_anonymous:
            return qs.none()
        if user.is_superuser or user.is_staff:
            return qs

        return qs.filter(
            Q(user=user) |
            Q(guardians__user=user) |
            Q(event__staff_members__user=user) |
            Q(booking__made_by=user)
        ).distinct()

    # ── Search ────────────────────────────────────────────────────────────────

    def _apply_search(self, qs: models.QuerySet) -> models.QuerySet: # TODO: in future replace with postgres full-text search for better performance and ranking
        '''
        Applies a search filter to the queryset based on the search term provided
        in the request data.

        Args:
            qs: The initial queryset to apply the search filter on.

        Returns:
            The queryset filtered by the search term.
        '''
        search = self.data.get('search')
        if not search:
            return qs
        return qs.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone_number__icontains=search) |
            Q(attendee_display_id__icontains=search)
        ).distinct()

    # ── Ordering ──────────────────────────────────────────────────────────────

    def _apply_ordering(self, qs: models.QuerySet) -> models.QuerySet:
        ordering = self.data.get('ordering') or '-created_at'
        return qs.order_by(ordering)

    # ── Demographics ──────────────────────────────────────────────────────────

    def _apply_demographics(self, qs: models.QuerySet) -> models.QuerySet:
        '''
        Applies demographic filters to the queryset based on the demographics data  

        Args:
            qs: The initial queryset to apply the demographic filters on.

        Returns:
            The queryset filtered by the demographic data.
        '''
        d = self.filter_data.get('demographics') or {}

        gender = d.get('gender')
        if gender:
            qs = qs.filter(gender__iexact=gender)

        age_min = d.get('age_min')
        if age_min is not None:
            max_dob = date.today() - relativedelta(years=int(age_min))
            qs = qs.filter(date_of_birth__lte=max_dob)

        age_max = d.get('age_max')
        if age_max is not None:
            min_dob = date.today() - relativedelta(years=int(age_max) + 1)
            qs = qs.filter(date_of_birth__gte=min_dob)

        is_minor = d.get('is_minor')
        if is_minor is not None:
            eighteen_ago = date.today() - relativedelta(years=18)
            if is_minor:
                qs = qs.filter(date_of_birth__gt=eighteen_ago)
            else:
                qs = qs.filter(date_of_birth__lte=eighteen_ago)

        organisations = d.get('organisation') or []
        if organisations:
            qs = qs.filter(organisations__organisation__id__in=organisations).distinct()

        areas = d.get('area_from') or []
        if areas:
            qs = qs.filter(area_from__id__in=areas).distinct()

        has_dietary = d.get('has_dietary_requirements')
        if has_dietary is not None:
            if has_dietary:
                qs = qs.filter(attendeedietaryrequirement__isnull=False).distinct()
            else:
                qs = qs.filter(attendeedietaryrequirement__isnull=True).distinct()

        dietary_ids = d.get('dietary_requirement') or []
        if dietary_ids:
            qs = qs.filter(attendeedietaryrequirement__dietary_requirement__id__in=dietary_ids).distinct()

        has_medical = d.get('has_medical_conditions')
        if has_medical is not None:
            if has_medical:
                qs = qs.filter(attendeemedicalcondition__isnull=False).distinct()
            else:
                qs = qs.filter(attendeemedicalcondition__isnull=True).distinct()

        medical_ids = d.get('medical_condition') or []
        if medical_ids:
            qs = qs.filter(attendeemedicalcondition__medical_condition__id__in=medical_ids).distinct()

        has_access = d.get('has_accessibility_requirements')
        if has_access is not None:
            if has_access:
                qs = qs.filter(attendeeaccessibilityrequirement__isnull=False).distinct()
            else:
                qs = qs.filter(attendeeaccessibilityrequirement__isnull=True).distinct()

        access_ids = d.get('accessibility_requirement') or []
        if access_ids:
            qs = qs.filter(
                attendeeaccessibilityrequirement__accessibility_requirement__id__in=access_ids
            ).distinct()

        has_emergency = d.get('has_emergency_contacts')
        if has_emergency is not None:
            if has_emergency:
                qs = qs.filter(emergency_contacts__isnull=False).distinct()
            else:
                qs = qs.filter(emergency_contacts__isnull=True).distinct()

        return qs

    # ── Status ────────────────────────────────────────────────────────────────

    def _apply_status(self, qs):
        s = self.filter_data.get('status') or {}

        is_checked_in = s.get('is_checked_in')
        if is_checked_in is not None:
            if is_checked_in:
                return qs.filter(
                    # event_attendances__check_in_time__isnull=False,
                    # event_attendances__check_out_time__isnull=True
                    check_in_records__action=CheckInAction.CHECK_IN,
                    check_in_records__scan_result=CheckInScanResult.SUCCESS
                ).distinct()
            elif is_checked_in is not None:
                return qs.exclude(
                    check_in_records__action=CheckInAction.CHECK_IN,
                    check_in_records__scan_result=CheckInScanResult.SUCCESS
                ).distinct()

        is_registered = s.get('is_registered')
        if is_registered is not None:
            if is_registered:
                qs = qs.filter(actions__action=AttendeeActionChoices.REGISTERED).distinct()
            else:
                qs = qs.exclude(actions__action=AttendeeActionChoices.REGISTERED).distinct()

        is_cancelled = s.get('is_cancelled')
        if is_cancelled is not None:
            if is_cancelled:
                qs = qs.filter(actions__action=AttendeeActionChoices.CANCELLED).distinct()
            else:
                qs = qs.exclude(actions__action=AttendeeActionChoices.CANCELLED).distinct()

        is_staff = s.get('is_staff')
        if is_staff is not None:
            if is_staff:
                qs = qs.filter(
                    user__isnull=False,
                    user__event_staff__event=models.F('event'),
                ).distinct()
            else:
                qs = qs.exclude(
                    user__isnull=False,
                    user__event_staff__event=models.F('event'),
                ).distinct()

        return qs

    # ── Registration questions ────────────────────────────────────────────────

    def _apply_registration_questions(self, qs):
        rq = self.filter_data.get('registration_questions') or {}
        conditions = rq.get('conditions') or []
        operator = rq.get('operator', 'AND')

        if not conditions:
            return qs

        if operator == 'AND':
            for condition in conditions:
                qs = self._apply_reg_question_condition(qs, condition)
        else:
            # OR: collect IDs from each condition and union them
            id_sets = []
            base_ids = set(qs.values_list('id', flat=True))
            for condition in conditions:
                matched = self._apply_reg_question_condition(
                    Attendee.objects.filter(id__in=base_ids), condition
                )
                id_sets.append(set(matched.values_list('id', flat=True)))
            union_ids = set().union(*id_sets) if id_sets else set()
            qs = qs.filter(id__in=union_ids)

        return qs

    def _apply_reg_question_condition(self, qs, condition: dict):
        q_id = condition['question_id']
        q_type = condition['type']

        # Must have answered this question
        qs = qs.filter(question_answers__question__id=q_id).distinct()

        if q_type in ('short_answer', 'long_answer'):
            contains = condition.get('contains')
            if contains:
                qs = qs.filter(question_answers__answer_text__icontains=contains).distinct()

        elif q_type in ('single_choice', 'multiple_choice'):
            opts = condition.get('selected_options') or []
            if opts:
                qs = qs.filter(
                    question_answers__selected_options__option__id__in=opts
                ).distinct()

        elif q_type == 'slider':
            mn = condition.get('min')
            mx = condition.get('max')
            if mn is not None:
                qs = qs.filter(
                    question_answers__question__question_type=EventQuestionTypeChoices.SLIDER,
                    question_answers__answer_text__gte=str(mn),
                ).distinct()
            if mx is not None:
                qs = qs.filter(
                    question_answers__question__question_type=EventQuestionTypeChoices.SLIDER,
                    question_answers__answer_text__lte=str(mx),
                ).distinct()

        elif q_type == 'upload':
            submitted_after = condition.get('submitted_after')
            if submitted_after:
                qs = qs.filter(question_answers__submitted_at__gte=submitted_after).distinct()
            submitted_before = condition.get('submitted_before')
            if submitted_before:
                qs = qs.filter(question_answers__submitted_at__lte=submitted_before).distinct()

        return qs

    # ── Event forms ──────────────────────────────────────────────────────────

    def _apply_forms(self, qs):
        forms_data = self.filter_data.get('forms') or {}
        conditions = forms_data.get('conditions') or []
        operator = forms_data.get('operator', 'AND')

        if not conditions:
            return qs

        if operator == 'AND':
            for condition in conditions:
                qs = self._apply_form_condition(qs, condition)
        else:
            # OR: collect IDs matched by any form condition then filter
            base_ids = set(qs.values_list('id', flat=True))
            id_sets = []
            for condition in conditions:
                matched = self._apply_form_condition(
                    Attendee.objects.filter(id__in=base_ids), condition
                )
                id_sets.append(set(matched.values_list('id', flat=True)))
            union_ids = set().union(*id_sets) if id_sets else set()
            qs = qs.filter(id__in=union_ids)

        return qs

    def _apply_form_condition(self, qs, condition: dict):
        form_id = condition['form']
        has_response = condition.get('has_response')
        response_complete = condition.get('response_complete')
        question_conditions = condition.get('questions') or []
        q_operator = condition.get('operator', 'AND')

        if has_response is True:
            qs = qs.filter(form_responses__form__id=form_id).distinct()
        elif has_response is False:
            qs = qs.exclude(form_responses__form__id=form_id).distinct()

        if response_complete is not None:
            qs = qs.filter(
                form_responses__form__id=form_id,
                form_responses__is_complete=response_complete,
            ).distinct()

        if not question_conditions:
            return qs

        if q_operator == 'AND':
            for q_cond in question_conditions:
                qs = self._apply_form_question_condition(qs, form_id, q_cond)
        else:
            base_ids = set(qs.values_list('id', flat=True))
            id_sets = []
            for q_cond in question_conditions:
                matched = self._apply_form_question_condition(
                    Attendee.objects.filter(id__in=base_ids), form_id, q_cond
                )
                id_sets.append(set(matched.values_list('id', flat=True)))
            union_ids = set().union(*id_sets) if id_sets else set()
            qs = qs.filter(id__in=union_ids)

        return qs

    def _apply_form_question_condition(self, qs, form_id, condition: dict):
        q_id = condition['question_id']
        q_type = condition['type']

        # Attendee must have an answer for this question within a response for this form
        qs = qs.filter(
            form_responses__form__id=form_id,
            form_responses__answers__question__id=q_id,
        ).distinct()

        if q_type in ('short_answer', 'long_answer', 'email', 'phone'):
            contains = condition.get('contains')
            if contains:
                qs = qs.filter(
                    form_responses__form__id=form_id,
                    form_responses__answers__question__id=q_id,
                    form_responses__answers__answer_text__icontains=contains,
                ).distinct()

        elif q_type in ('single_choice', 'multiple_choice'):
            opts = condition.get('selected_options') or []
            if opts:
                qs = qs.filter(
                    form_responses__form__id=form_id,
                    form_responses__answers__question__id=q_id,
                    form_responses__answers__selected_options__option__id__in=opts,
                ).distinct()

        elif q_type in ('slider', 'rating'):
            mn = condition.get('min')
            mx = condition.get('max')
            if mn is not None:
                matching_ids = (
                    Attendee.objects.filter(
                        form_responses__form__id=form_id,
                        form_responses__answers__question__id=q_id,
                        form_responses__answers__answer_text__regex=r'^-?\d+$',
                    )
                    .annotate(numeric_val=Cast(
                        'form_responses__answers__answer_text', output_field=IntegerField()
                    ))
                    .filter(numeric_val__gte=mn)
                    .values('id')
                )
                qs = qs.filter(id__in=matching_ids).distinct()
            if mx is not None:
                matching_ids = (
                    Attendee.objects.filter(
                        form_responses__form__id=form_id,
                        form_responses__answers__question__id=q_id,
                        form_responses__answers__answer_text__regex=r'^-?\d+$',
                    )
                    .annotate(numeric_val=Cast(
                        'form_responses__answers__answer_text', output_field=IntegerField()
                    ))
                    .filter(numeric_val__lte=mx)
                    .values('id')
                )
                qs = qs.filter(id__in=matching_ids).distinct()

        elif q_type == 'date':
            date_after = condition.get('date_after')
            date_before = condition.get('date_before')
            if date_after:
                date_str = date_after.isoformat() if hasattr(date_after, 'isoformat') else str(date_after)
                qs = (
                    qs.annotate(
                        _date_after_cast=Case(
                            When(
                                form_responses__form__id=form_id,
                                form_responses__answers__question__id=q_id,
                                form_responses__answers__question__question_type=EventFormQuestionTypeChoices.DATE,
                                then=Cast(F('form_responses__answers__answer_text'), DateField()),
                            ),
                            default=Value(None),
                            output_field=DateField(),
                        )
                    )
                    .filter(
                        form_responses__form__id=form_id,
                        form_responses__answers__question__id=q_id,
                        _date_after_cast__gte=date_str,
                    )
                    .distinct()
                )
            if date_before:
                date_str = date_before.isoformat() if hasattr(date_before, 'isoformat') else str(date_before)
                qs = (
                    qs.annotate(
                        _date_before_cast=Case(
                            When(
                                form_responses__form__id=form_id,
                                form_responses__answers__question__id=q_id,
                                form_responses__answers__question__question_type=EventFormQuestionTypeChoices.DATE,
                                then=Cast(F('form_responses__answers__answer_text'), DateField()),
                            ),
                            default=Value(None),
                            output_field=DateField(),
                        )
                    )
                    .filter(
                        form_responses__form__id=form_id,
                        form_responses__answers__question__id=q_id,
                        _date_before_cast__lte=date_str,
                    )
                    .distinct()
                )

        elif q_type == 'time':
            time_after = condition.get('time_after')
            time_before = condition.get('time_before')
            if time_after:
                time_str = time_after.isoformat() if hasattr(time_after, 'isoformat') else str(time_after)
                qs = (
                    qs.annotate(
                        _time_after_cast=Case(
                            When(
                                form_responses__form__id=form_id,
                                form_responses__answers__question__id=q_id,
                                form_responses__answers__question__question_type=EventFormQuestionTypeChoices.TIME,
                                then=Cast(F('form_responses__answers__answer_text'), TimeField()),
                            ),
                            default=Value(None),
                            output_field=TimeField(),
                        )
                    )
                    .filter(
                        form_responses__form__id=form_id,
                        form_responses__answers__question__id=q_id,
                        _time_after_cast__gte=time_str,
                    )
                    .distinct()
                )
            if time_before:
                time_str = time_before.isoformat() if hasattr(time_before, 'isoformat') else str(time_before)
                qs = (
                    qs.annotate(
                        _time_before_cast=Case(
                            When(
                                form_responses__form__id=form_id,
                                form_responses__answers__question__id=q_id,
                                form_responses__answers__question__question_type=EventFormQuestionTypeChoices.TIME,
                                then=Cast(F('form_responses__answers__answer_text'), TimeField()),
                            ),
                            default=Value(None),
                            output_field=TimeField(),
                        )
                    )
                    .filter(
                        form_responses__form__id=form_id,
                        form_responses__answers__question__id=q_id,
                        _time_before_cast__lte=time_str,
                    )
                    .distinct()
                )

        elif q_type == 'upload':
            submitted_after = condition.get('submitted_after')
            if submitted_after:
                qs = qs.filter(
                    form_responses__form__id=form_id,
                    form_responses__answers__question__id=q_id,
                    form_responses__answers__submitted_at__gte=submitted_after,
                ).distinct()
            submitted_before = condition.get('submitted_before')
            if submitted_before:
                qs = qs.filter(
                    form_responses__form__id=form_id,
                    form_responses__answers__question__id=q_id,
                    form_responses__answers__submitted_at__lte=submitted_before,
                ).distinct()

        return qs

    # ── Orders ────────────────────────────────────────────────────────────────

    def _apply_orders(self, qs):
        o = self.filter_data.get('orders') or {}

        has_orders = o.get('has_orders')
        if has_orders is not None:
            if has_orders:
                qs = qs.filter(orders__isnull=False).distinct()
            else:
                qs = qs.filter(orders__isnull=True).distinct()

        order_status = [v for v in (o.get('order_status') or []) if v]
        if order_status:
            valid = {c[0] for c in OrderStatusChoices.choices}
            values = [v for v in order_status if v in valid]
            if values:
                qs = qs.filter(orders__status__in=values).distinct()

        order_status_not = [v for v in (o.get('order_status_not') or []) if v]
        if order_status_not:
            valid = {c[0] for c in OrderStatusChoices.choices}
            values = [v for v in order_status_not if v in valid]
            if values:
                qs = qs.exclude(orders__status__in=values).distinct()

        purchased_product = o.get('purchased_product') or []
        if purchased_product:
            qs = qs.filter(orders__order_items__product_variant__id__in=purchased_product).distinct()

        purchased_product_title = o.get('purchased_product_title')
        if purchased_product_title:
            qs = qs.filter(
                orders__order_items__product_variant__product__title__icontains=purchased_product_title
            ).distinct()

        order_total_min = o.get('order_total_min')
        if order_total_min is not None:
            qs = qs.filter(orders__total_amount__gte=order_total_min).distinct()

        order_total_max = o.get('order_total_max')
        if order_total_max is not None:
            qs = qs.filter(orders__total_amount__lte=order_total_max).distinct()

        order_created_after = o.get('order_created_after')
        if order_created_after:
            qs = qs.filter(orders__created_at__gte=order_created_after).distinct()

        order_created_before = o.get('order_created_before')
        if order_created_before:
            qs = qs.filter(orders__created_at__lte=order_created_before).distinct()

        order_reference_id = o.get('order_reference_id')
        if order_reference_id:
            qs = qs.filter(orders__order_reference_id__icontains=order_reference_id).distinct()

        has_completed_orders = o.get('has_completed_orders')
        if has_completed_orders is not None:
            if has_completed_orders:
                qs = qs.filter(orders__status=OrderStatusChoices.COMPLETED).distinct()
            else:
                qs = qs.exclude(orders__status=OrderStatusChoices.COMPLETED).distinct()

        has_pending_orders = o.get('has_pending_orders')
        if has_pending_orders is not None:
            if has_pending_orders:
                qs = qs.filter(
                    Q(orders__status=OrderStatusChoices.PENDING) |
                    Q(orders__status=OrderStatusChoices.PROCESSING)
                ).distinct()
            else:
                qs = qs.exclude(
                    Q(orders__status=OrderStatusChoices.PENDING) |
                    Q(orders__status=OrderStatusChoices.PROCESSING)
                ).distinct()

        return qs

    # ── Payments ──────────────────────────────────────────────────────────────

    def _apply_payments(self, qs):
        from apps.payments.models import Payment, Discount

        p = self.filter_data.get('payments') or {}

        has_payments = p.get('has_payments')
        if has_payments is not None:
            matched = _filter_attendees_by_payment_queryset(qs, Payment.objects.all())
            if has_payments:
                qs = matched
            else:
                qs = qs.exclude(id__in=matched.values_list('id', flat=True)).distinct()

        payment_ids = p.get('payment_id') or []
        if payment_ids:
            qs = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(payment_id__in=payment_ids)
            )

        payment_reference = p.get('payment_reference')
        if payment_reference:
            qs = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(payment_reference__icontains=payment_reference)
            )

        bank_transfer_reference = p.get('bank_transfer_reference')
        if bank_transfer_reference:
            qs = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(bank_transfer_reference__icontains=bank_transfer_reference)
            )

        payment_status = [v for v in (p.get('payment_status') or []) if v]
        if payment_status:
            valid = {c[0] for c in PaymentStatusChoices.choices}
            values = [v for v in payment_status if v in valid]
            if values:
                payment_target = p.get('payment_target')
                targets = {payment_target} if payment_target in {'booking', 'order', 'ticket'} else {'booking'}
                qs = _filter_attendees_by_payment_queryset(
                    qs, Payment.objects.filter(status__in=values), targets=targets
                )

        payment_target = p.get('payment_target')
        if payment_target and not payment_status:
            qs = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.all(), targets={payment_target}
            )

        payment_method_type = [v for v in (p.get('payment_method_type') or []) if v]
        if payment_method_type:
            valid = {c[0] for c in PaymentMethodTypeChoices.choices}
            values = [v for v in payment_method_type if v in valid]
            if values:
                qs = _filter_attendees_by_payment_queryset(
                    qs, Payment.objects.filter(method__method_type__in=values)
                )

        payment_method_title = p.get('payment_method_title')
        if payment_method_title:
            qs = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(method__title__icontains=payment_method_title)
            )

        has_refunds = p.get('has_refunds')
        if has_refunds is not None:
            matched = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(refund_requests__isnull=False).distinct()
            )
            if has_refunds:
                qs = matched
            else:
                qs = qs.exclude(id__in=matched.values_list('id', flat=True)).distinct()

        refund_status = [v for v in (p.get('refund_status') or []) if v]
        if refund_status:
            valid = {c[0] for c in VerificationStatus.choices}
            values = [v for v in refund_status if v in valid]
            if values:
                qs = _filter_attendees_by_payment_queryset(
                    qs, Payment.objects.filter(refund_requests__verification_status__in=values).distinct()
                )

        refund_is_active = p.get('refund_is_active')
        if refund_is_active is not None:
            qs = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(refund_requests__is_active=refund_is_active).distinct()
            )

        has_donations = p.get('has_donations')
        if has_donations is not None:
            matched = _filter_attendees_by_payment_queryset(
                qs, Payment.objects.filter(donations__isnull=False).distinct()
            )
            if has_donations:
                qs = matched
            else:
                qs = qs.exclude(id__in=matched.values_list('id', flat=True)).distinct()

        donation_status = [v for v in (p.get('donation_status') or []) if v]
        if donation_status:
            valid = {c[0] for c in VerificationStatus.choices}
            values = [v for v in donation_status if v in valid]
            if values:
                qs = _filter_attendees_by_payment_queryset(
                    qs, Payment.objects.filter(donations__verification_status__in=values).distinct()
                )

        has_discounts_used = p.get('has_discounts_used')
        if has_discounts_used is not None:
            matched = _filter_attendees_by_discount_queryset(qs, Discount.objects.all())
            if has_discounts_used:
                qs = matched
            else:
                qs = qs.exclude(id__in=matched.values_list('id', flat=True)).distinct()

        discount_ids = p.get('discount_id') or []
        if discount_ids:
            qs = _filter_attendees_by_discount_queryset(
                qs, Discount.objects.filter(discount_id__in=discount_ids)
            )

        discount_name = p.get('discount_name')
        if discount_name:
            qs = _filter_attendees_by_discount_queryset(
                qs, Discount.objects.filter(name__icontains=discount_name)
            )

        return qs

    # ── Advanced ──────────────────────────────────────────────────────────────

    def _apply_advanced(self, qs):
        a = self.filter_data.get('advanced') or {}

        relationship = a.get('relationship_to_user')
        if relationship:
            qs = qs.filter(relationship_to_user=relationship)

        self_registered = a.get('self_registered')
        if self_registered is not None:
            if self_registered:
                qs = qs.filter(
                    relationship_to_user=AttendeeRelationship.SELF, user__isnull=False
                )
            else:
                qs = qs.exclude(
                    relationship_to_user=AttendeeRelationship.SELF, user__isnull=False
                )

        has_booking = a.get('has_booking')
        if has_booking is not None:
            if has_booking:
                qs = qs.filter(booking__isnull=False)
            else:
                qs = qs.filter(booking__isnull=True)

        booking_ids = a.get('booking') or []
        if booking_ids:
            qs = qs.filter(booking__booking_id__in=booking_ids).distinct()

        dob_after = a.get('date_of_birth_after')
        if dob_after:
            qs = qs.filter(date_of_birth__gte=dob_after)

        dob_before = a.get('date_of_birth_before')
        if dob_before:
            qs = qs.filter(date_of_birth__lte=dob_before)

        created_after = a.get('created_after')
        if created_after:
            qs = qs.filter(created_at__gte=created_after)

        created_before = a.get('created_before')
        if created_before:
            qs = qs.filter(created_at__lte=created_before)

        return qs

    # ── Entry point ───────────────────────────────────────────────────────────

    def get_queryset(self):
        qs = self._base_queryset()
        qs = self._apply_search(qs)
        qs = self._apply_demographics(qs)
        qs = self._apply_status(qs)
        qs = self._apply_registration_questions(qs)
        qs = self._apply_forms(qs)
        qs = self._apply_orders(qs)
        qs = self._apply_payments(qs)
        qs = self._apply_advanced(qs)
        qs = self._apply_ordering(qs)
        return qs

    # ── Pagination helper ────────────────────────────────────────────────────

    def paginate(self, qs: models.QuerySet) -> typing.Tuple[models.QuerySet, typing.Dict[str, typing.Any]]:
        """Return (items, pagination_meta) for the current page."""
        page = int(self.data.get('page') or 1)
        page_size = int(self.data.get('page_size') or 25)
        page_size = min(page_size, 200)

        total = qs.count()
        total_pages = math.ceil(total / page_size) if page_size else 1
        offset = (page - 1) * page_size
        items = qs[offset: offset + page_size]

        return items, {
            'count': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_previous': page > 1,
        }
