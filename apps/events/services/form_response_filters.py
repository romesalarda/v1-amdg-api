"""
FormResponseFilterService

Applies a structured filter body (from POST /api/event-form-responses/filter/)
to an EventFormResponse queryset.

Strategy:
  1. Start with EventFormResponse objects for the requested form, scoped by user perms.
  2. Apply attendee demographic/status filters by traversing the attendee__ FK join.
  3. Apply per-question answer conditions directly on the response's answers.
  4. Return paginated results.
"""
from datetime import date

from dateutil.relativedelta import relativedelta
from django.core.paginator import EmptyPage, Paginator
from django.db import models
from django.db.models import Q, F, IntegerField, DateField, TimeField, Value, Case, When
from django.db.models.functions import Cast
from rest_framework.request import Request

from apps.events.models import EventFormResponse, EventFormQuestionTypeChoices
from apps.attendee.models import AttendeeActionChoices
from apps.attendee.models.checkin import CheckInAction, CheckInScanResult


class FormResponseFilterService:
    """
    Apply a validated filter body to an EventFormResponse queryset.

    Instantiate with the request and validated data from
    FormResponseFilterRequestSerializer, then call get_queryset().
    """

    def __init__(self, request: Request, validated_data: dict):
        self.request = request
        self.data = validated_data

    # ── Base queryset ─────────────────────────────────────────────────────────

    def _base_queryset(self) -> models.QuerySet:
        user = self.request.user
        form_id = self.data['form']

        qs = EventFormResponse.objects.select_related(
            'form__event', 'attendee'
        ).prefetch_related(
            'answers__question', 'answers__selected_options__option'
        ).filter(form__id=form_id)

        if user.is_anonymous:
            return qs.none()
        if user.is_superuser or user.is_staff:
            return qs

        # Non-staff: scope to responses the user is connected to
        return qs.filter(
            Q(attendee__booking__user=user) |
            Q(form__event__staff_members__user=user)
        ).distinct()

    # ── Demographics ──────────────────────────────────────────────────────────

    def _apply_demographics(self, qs: models.QuerySet) -> models.QuerySet:
        d = (self.data.get('demographics') or {})

        gender = d.get('gender')
        if gender:
            qs = qs.filter(attendee__gender__iexact=gender)

        age_min = d.get('age_min')
        if age_min is not None:
            max_dob = date.today() - relativedelta(years=int(age_min))
            qs = qs.filter(attendee__date_of_birth__lte=max_dob)

        age_max = d.get('age_max')
        if age_max is not None:
            min_dob = date.today() - relativedelta(years=int(age_max) + 1)
            qs = qs.filter(attendee__date_of_birth__gte=min_dob)

        is_minor = d.get('is_minor')
        if is_minor is not None:
            eighteen_ago = date.today() - relativedelta(years=18)
            if is_minor:
                qs = qs.filter(attendee__date_of_birth__gt=eighteen_ago)
            else:
                qs = qs.filter(attendee__date_of_birth__lte=eighteen_ago)

        organisations = d.get('organisation') or []
        if organisations:
            qs = qs.filter(
                attendee__organisations__organisation__id__in=organisations
            ).distinct()

        areas = d.get('area_from') or []
        if areas:
            qs = qs.filter(attendee__area_from__id__in=areas).distinct()

        chapters = d.get('chapter_from') or []
        if chapters:
            qs = qs.filter(
                attendee__area_from__chapter__id__in=chapters
            ).distinct()

        clusters = d.get('cluster_from') or []
        if clusters:
            qs = qs.filter(
                attendee__area_from__chapter__cluster__id__in=clusters
            ).distinct()

        countries = d.get('country_from') or []
        if countries:
            qs = qs.filter(
                attendee__area_from__chapter__cluster__country__id__in=countries
            ).distinct()

        has_dietary = d.get('has_dietary_requirements')
        if has_dietary is not None:
            if has_dietary:
                qs = qs.filter(
                    attendee__attendeedietaryrequirement__isnull=False
                ).distinct()
            else:
                qs = qs.filter(
                    attendee__attendeedietaryrequirement__isnull=True
                ).distinct()

        dietary_ids = d.get('dietary_requirement') or []
        if dietary_ids:
            qs = qs.filter(
                attendee__attendeedietaryrequirement__dietary_requirement__id__in=dietary_ids
            ).distinct()

        has_medical = d.get('has_medical_conditions')
        if has_medical is not None:
            if has_medical:
                qs = qs.filter(
                    attendee__attendeemedicalcondition__isnull=False
                ).distinct()
            else:
                qs = qs.filter(
                    attendee__attendeemedicalcondition__isnull=True
                ).distinct()

        medical_ids = d.get('medical_condition') or []
        if medical_ids:
            qs = qs.filter(
                attendee__attendeemedicalcondition__medical_condition__id__in=medical_ids
            ).distinct()

        has_access = d.get('has_accessibility_requirements')
        if has_access is not None:
            if has_access:
                qs = qs.filter(
                    attendee__attendeeaccessibilityrequirement__isnull=False
                ).distinct()
            else:
                qs = qs.filter(
                    attendee__attendeeaccessibilityrequirement__isnull=True
                ).distinct()

        access_ids = d.get('accessibility_requirement') or []
        if access_ids:
            qs = qs.filter(
                attendee__attendeeaccessibilityrequirement__accessibility_requirement__id__in=access_ids
            ).distinct()

        return qs

    # ── Status ────────────────────────────────────────────────────────────────

    def _apply_status(self, qs: models.QuerySet) -> models.QuerySet:
        s = (self.data.get('status') or {})

        is_checked_in = s.get('is_checked_in')
        if is_checked_in is not None:
            if is_checked_in:
                qs = qs.filter(
                    attendee__check_in_records__action=CheckInAction.CHECK_IN,
                    attendee__check_in_records__scan_result=CheckInScanResult.SUCCESS,
                ).distinct()
            else:
                qs = qs.exclude(
                    attendee__check_in_records__action=CheckInAction.CHECK_IN,
                    attendee__check_in_records__scan_result=CheckInScanResult.SUCCESS,
                ).distinct()

        is_registered = s.get('is_registered')
        if is_registered is not None:
            if is_registered:
                qs = qs.filter(
                    attendee__actions__action=AttendeeActionChoices.REGISTERED
                ).distinct()
            else:
                qs = qs.exclude(
                    attendee__actions__action=AttendeeActionChoices.REGISTERED
                ).distinct()

        is_cancelled = s.get('is_cancelled')
        if is_cancelled is not None:
            if is_cancelled:
                qs = qs.filter(
                    attendee__actions__action=AttendeeActionChoices.CANCELLED
                ).distinct()
            else:
                qs = qs.exclude(
                    attendee__actions__action=AttendeeActionChoices.CANCELLED
                ).distinct()

        is_staff = s.get('is_staff')
        if is_staff is not None:
            if is_staff:
                qs = qs.filter(
                    attendee__user__isnull=False,
                    attendee__user__event_staff__event=F('form__event'),
                ).distinct()
            else:
                qs = qs.exclude(
                    attendee__user__isnull=False,
                    attendee__user__event_staff__event=F('form__event'),
                ).distinct()

        return qs

    # ── Question conditions ───────────────────────────────────────────────────

    def _apply_question_filter(self, qs: models.QuerySet) -> models.QuerySet:
        qf = self.data.get('question_filter') or {}
        conditions = qf.get('conditions') or []
        operator = qf.get('operator', 'AND')

        if not conditions:
            return qs

        if operator == 'AND':
            for cond in conditions:
                qs = self._apply_question_condition(qs, cond)
        else:
            # OR: each condition matched independently; union the IDs
            base_ids = list(qs.values_list('id', flat=True))
            id_sets = []
            for cond in conditions:
                matched = self._apply_question_condition(
                    EventFormResponse.objects.filter(id__in=base_ids), cond
                )
                id_sets.append(set(matched.values_list('id', flat=True)))
            union_ids = set().union(*id_sets) if id_sets else set()
            qs = qs.filter(id__in=union_ids)

        return qs

    def _apply_question_condition(self, qs: models.QuerySet, condition: dict) -> models.QuerySet:
        q_id = condition['question_id']
        q_type = condition['type']

        # Attendee must have an answer for this question in this response
        qs = qs.filter(answers__question__id=q_id).distinct()

        if q_type in ('short_answer', 'long_answer', 'email', 'phone'):
            contains = condition.get('contains')
            if contains:
                qs = qs.filter(
                    answers__question__id=q_id,
                    answers__answer_text__icontains=contains,
                ).distinct()

        elif q_type in ('single_choice', 'multiple_choice'):
            opts = condition.get('selected_options') or []
            if opts:
                qs = qs.filter(
                    answers__question__id=q_id,
                    answers__selected_options__option__id__in=opts,
                ).distinct()

        elif q_type in ('slider', 'rating'):
            mn = condition.get('min')
            mx = condition.get('max')
            if mn is not None:
                matching_ids = (
                    qs.filter(
                        answers__question__id=q_id,
                        answers__answer_text__regex=r'^-?\d+$',
                    )
                    .annotate(
                        _numeric_val=Cast(
                            'answers__answer_text', output_field=IntegerField()
                        )
                    )
                    .filter(_numeric_val__gte=mn)
                    .values('id')
                )
                qs = qs.filter(id__in=matching_ids).distinct()
            if mx is not None:
                matching_ids = (
                    qs.filter(
                        answers__question__id=q_id,
                        answers__answer_text__regex=r'^-?\d+$',
                    )
                    .annotate(
                        _numeric_val=Cast(
                            'answers__answer_text', output_field=IntegerField()
                        )
                    )
                    .filter(_numeric_val__lte=mx)
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
                                answers__question__id=q_id,
                                answers__question__question_type=EventFormQuestionTypeChoices.DATE,
                                then=Cast(F('answers__answer_text'), DateField()),
                            ),
                            default=Value(None),
                            output_field=DateField(),
                        )
                    )
                    .filter(
                        answers__question__id=q_id,
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
                                answers__question__id=q_id,
                                answers__question__question_type=EventFormQuestionTypeChoices.DATE,
                                then=Cast(F('answers__answer_text'), DateField()),
                            ),
                            default=Value(None),
                            output_field=DateField(),
                        )
                    )
                    .filter(
                        answers__question__id=q_id,
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
                                answers__question__id=q_id,
                                answers__question__question_type=EventFormQuestionTypeChoices.TIME,
                                then=Cast(F('answers__answer_text'), TimeField()),
                            ),
                            default=Value(None),
                            output_field=TimeField(),
                        )
                    )
                    .filter(
                        answers__question__id=q_id,
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
                                answers__question__id=q_id,
                                answers__question__question_type=EventFormQuestionTypeChoices.TIME,
                                then=Cast(F('answers__answer_text'), TimeField()),
                            ),
                            default=Value(None),
                            output_field=TimeField(),
                        )
                    )
                    .filter(
                        answers__question__id=q_id,
                        _time_before_cast__lte=time_str,
                    )
                    .distinct()
                )

        elif q_type == 'upload':
            submitted_after = condition.get('submitted_after')
            if submitted_after:
                qs = qs.filter(
                    answers__question__id=q_id,
                    answers__submitted_at__gte=submitted_after,
                ).distinct()
            submitted_before = condition.get('submitted_before')
            if submitted_before:
                qs = qs.filter(
                    answers__question__id=q_id,
                    answers__submitted_at__lte=submitted_before,
                ).distinct()

        return qs

    # ── Search ────────────────────────────────────────────────────────────────

    def _apply_search(self, qs: models.QuerySet) -> models.QuerySet:
        search = self.data.get('search')
        if not search:
            return qs
        return qs.filter(
            Q(attendee__first_name__icontains=search) |
            Q(attendee__last_name__icontains=search) |
            Q(attendee__email__icontains=search) |
            Q(attendee__attendee_display_id__icontains=search)
        ).distinct()

    # ── Ordering ──────────────────────────────────────────────────────────────

    def _apply_ordering(self, qs: models.QuerySet) -> models.QuerySet:
        ordering = self.data.get('ordering') or '-submitted_at'
        return qs.order_by(ordering)

    # ── Main entrypoint ───────────────────────────────────────────────────────

    def get_queryset(self) -> models.QuerySet:
        qs = self._base_queryset()
        qs = self._apply_demographics(qs)
        qs = self._apply_status(qs)
        qs = self._apply_question_filter(qs)
        qs = self._apply_search(qs)
        qs = self._apply_ordering(qs)
        return qs

    def paginate(self, qs: models.QuerySet) -> tuple[list, dict]:
        page_num = max(1, int(self.data.get('page') or 1))
        page_size = max(1, min(200, int(self.data.get('page_size') or 25)))

        paginator = Paginator(qs, page_size)
        try:
            page_obj = paginator.page(page_num)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        return list(page_obj.object_list), {
            'count': paginator.count,
            'total_pages': paginator.num_pages,
            'page': page_obj.number,
            'page_size': page_size,
        }
