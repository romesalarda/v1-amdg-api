"""
Organisation Statistics Calculation Module

Provides organisation-focused analytics for admin dashboards.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.attendee.models import Attendee
from apps.bookings.models import Booking
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventStatusChoices
from apps.locations.models import AreaLocation
from apps.organisations.models import (
	EventSponsorPackage,
	Leader,
	Organisation,
	OrganisationControl,
	UserOrganisationMembership,
)
from apps.payments.models import Payment, PaymentStatusChoices
from apps.payments.models.donations import Donation


LEADER_LOCATION_TYPE_LABELS = {
	"countrylocation": "Country",
	"clusterlocation": "Cluster",
	"chapterlocation": "Chapter",
	"arealocation": "Area",
}


def _base_events_queryset(organisation_ids: list[int] | None):
	queryset = Event.objects.filter(deleted_at__isnull=True)
	if organisation_ids is not None:
		if not organisation_ids:
			return Event.objects.none()
		queryset = queryset.filter(organisation_id__in=organisation_ids)
	return queryset


def _base_payments_queryset(
	organisation_ids: list[int] | None,
	date_from=None,
	date_to=None,
):
	queryset = Payment.objects.filter(
		event__deleted_at__isnull=True,
		status=PaymentStatusChoices.COMPLETED,
	)
	if organisation_ids is not None:
		if not organisation_ids:
			return Payment.objects.none()
		queryset = queryset.filter(event__organisation_id__in=organisation_ids)
	if date_from:
		queryset = queryset.filter(created_at__date__gte=date_from)
	if date_to:
		queryset = queryset.filter(created_at__date__lte=date_to)
	return queryset


def _get_revenue_sources(payments_queryset):
	booking_type = ContentType.objects.get_for_model(Booking)
	donation_type = ContentType.objects.get_for_model(Donation)
	sponsor_package_type = ContentType.objects.get_for_model(EventSponsorPackage)

	booking_qs = payments_queryset.filter(target_type=booking_type)
	donation_qs = payments_queryset.filter(target_type=donation_type)
	sponsorship_qs = payments_queryset.filter(target_type=sponsor_package_type)
	known_type_ids = [booking_type.id, donation_type.id, sponsor_package_type.id]
	other_qs = payments_queryset.exclude(target_type_id__in=known_type_ids)

	def as_row(label, qs):
		amount = qs.aggregate(total=Coalesce(Sum("base_amount"), Decimal("0.00")))["total"]
		return {
			"label": label,
			"value": qs.count(),
			"amount": float(amount),
		}

	return [
		as_row("Bookings", booking_qs),
		as_row("Donations", donation_qs),
		as_row("Sponsorships", sponsorship_qs),
		as_row("Other", other_qs),
	]


def calculate_overview_statistics(
	organisation_ids: list[int] | None = None,
	date_from=None,
	date_to=None,
) -> dict[str, Any]:
	events_qs = _base_events_queryset(organisation_ids)
	payments_qs = _base_payments_queryset(organisation_ids, date_from=date_from, date_to=date_to)

	if date_from:
		events_qs = events_qs.filter(start_datetime__date__gte=date_from)
	if date_to:
		events_qs = events_qs.filter(start_datetime__date__lte=date_to)

	members_qs = UserOrganisationMembership.objects.all()
	controllers_qs = OrganisationControl.objects.all()
	if organisation_ids is not None:
		if not organisation_ids:
			members_qs = UserOrganisationMembership.objects.none()
			controllers_qs = OrganisationControl.objects.none()
		else:
			members_qs = members_qs.filter(organisation_id__in=organisation_ids)
			controllers_qs = controllers_qs.filter(organisation_id__in=organisation_ids)

	attendee_qs = Attendee.objects.filter(
		event__in=events_qs,
		deleted_at__isnull=True,
	)

	total_events = events_qs.count()
	total_attendees = attendee_qs.count()

	total_revenue = payments_qs.aggregate(total=Coalesce(Sum("base_amount"), Decimal("0.00")))["total"]
	total_completed_payments = payments_qs.count()

	avg_payment = payments_qs.aggregate(avg=Avg("base_amount"))["avg"] or Decimal("0.00")
	avg_attendees = float(total_attendees / total_events) if total_events else 0.0
	avg_event_revenue = float(total_revenue / total_events) if total_events else 0.0

	event_status_distribution_qs = events_qs.values("status").annotate(count=Count("id")).order_by("-count")
	event_status_distribution = []
	for row in event_status_distribution_qs:
		event_status_distribution.append(
			{
				"label": dict(EventStatusChoices.choices).get(row["status"], row["status"]),
				"code": row["status"],
				"value": row["count"],
			}
		)

	payment_status_distribution_qs = payments_qs.values("status").annotate(count=Count("id")).order_by("-count")
	payment_status_distribution = []
	for row in payment_status_distribution_qs:
		payment_status_distribution.append(
			{
				"label": dict(PaymentStatusChoices.choices).get(row["status"], row["status"]),
				"code": row["status"],
				"value": row["count"],
			}
		)

	organisations_qs = Organisation.objects.all()
	if organisation_ids is not None:
		organisations_qs = organisations_qs.filter(id__in=organisation_ids)

	return {
		"total_organisations": organisations_qs.count(),
		"total_events": total_events,
		"active_events": events_qs.filter(status__in=[EventStatusChoices.OPEN, EventStatusChoices.IN_PROGRESS]).count(),
		"upcoming_events": events_qs.filter(start_datetime__gt=timezone.now()).count(),
		"completed_events": events_qs.filter(status=EventStatusChoices.COMPLETED).count(),
		"total_attendees": total_attendees,
		"average_attendees_per_event": round(avg_attendees, 2),
		"total_members": members_qs.count(),
		"verified_members": members_qs.exclude(verified_at__isnull=True).count(),
		"total_controllers": controllers_qs.count(),
		"total_revenue": float(total_revenue),
		"total_completed_payments": total_completed_payments,
		"average_payment_value": float(avg_payment),
		"average_event_revenue": round(avg_event_revenue, 2),
		"revenue_sources": _get_revenue_sources(payments_qs),
		"event_status_distribution": event_status_distribution,
		"payment_status_distribution": payment_status_distribution,
	}


def calculate_leader_distribution(organisation_ids: list[int] | None = None) -> dict[str, Any]:
	leaders_qs = Leader.objects.all()
	if organisation_ids is not None:
		if not organisation_ids:
			leaders_qs = Leader.objects.none()
		else:
			leaders_qs = leaders_qs.filter(organisation_id__in=organisation_ids)

	total = leaders_qs.count()

	grouped = leaders_qs.values("target_type__model").annotate(count=Count("id")).order_by("-count")
	distribution = []
	for row in grouped:
		model_name = row["target_type__model"]
		value = row["count"]
		distribution.append(
			{
				"code": model_name,
				"label": LEADER_LOCATION_TYPE_LABELS.get(model_name, model_name.title()),
				"value": value,
				"percentage": round((value / total) * 100, 2) if total else 0,
			}
		)

	area_rows = leaders_qs.filter(target_type__model="arealocation").values("target_id").annotate(
		value=Count("id")
	).order_by("-value")
	area_ids = [int(row["target_id"]) for row in area_rows if str(row["target_id"]).isdigit()]
	area_names = {
		area.id: area.area_name
		for area in AreaLocation.objects.filter(id__in=area_ids)
	}
	area_distribution = []
	for row in area_rows:
		target_id = row["target_id"]
		area_id = int(target_id) if str(target_id).isdigit() else None
		area_distribution.append(
			{
				"area_id": target_id,
				"label": area_names.get(area_id, f"Area #{target_id}"),
				"value": row["value"],
			}
		)

	return {
		"total_leaders": total,
		"distribution": distribution,
		"area_distribution": area_distribution,
	}


def calculate_event_performance_statistics(
	organisation_ids: list[int] | None = None,
	date_from=None,
	date_to=None,
	limit: int = 20,
) -> dict[str, Any]:
	events_qs = _base_events_queryset(organisation_ids)
	if date_from:
		events_qs = events_qs.filter(start_datetime__date__gte=date_from)
	if date_to:
		events_qs = events_qs.filter(start_datetime__date__lte=date_to)

	annotated = events_qs.annotate(
		attendee_count=Count("attendees", filter=Q(attendees__deleted_at__isnull=True), distinct=True),
		completed_payment_count=Count("payments", filter=Q(payments__status=PaymentStatusChoices.COMPLETED), distinct=True),
		completed_payment_amount=Coalesce(
			Sum("payments__base_amount", filter=Q(payments__status=PaymentStatusChoices.COMPLETED)),
			Decimal("0.00"),
		),
	).order_by("-completed_payment_amount", "-attendee_count")

	rows = []
	for event in annotated[:limit]:
		rows.append(
			{
				"event_id": str(event.event_id),
				"event_title": event.title,
				"event_status": event.status,
				"attendee_count": event.attendee_count,
				"completed_payment_count": event.completed_payment_count,
				"completed_payment_amount": float(event.completed_payment_amount),
				"average_payment_value": (
					round(float(event.completed_payment_amount) / event.completed_payment_count, 2)
					if event.completed_payment_count
					else 0.0
				),
			}
		)

	totals = {
		"total_events": events_qs.count(),
		"total_attendees": sum(row["attendee_count"] for row in rows),
		"total_completed_payment_count": sum(row["completed_payment_count"] for row in rows),
		"total_completed_payment_amount": round(sum(row["completed_payment_amount"] for row in rows), 2),
	}
	totals["average_attendees_per_event"] = (
		round(totals["total_attendees"] / totals["total_events"], 2)
		if totals["total_events"]
		else 0.0
	)

	return {
		"events": rows,
		"totals": totals,
		"limit": limit,
	}


def calculate_payments_by_source_statistics(
	organisation_ids: list[int] | None = None,
	date_from=None,
	date_to=None,
) -> dict[str, Any]:
	payments_qs = _base_payments_queryset(organisation_ids, date_from=date_from, date_to=date_to)
	sources = _get_revenue_sources(payments_qs)

	donation_total = Donation.objects.filter(
		payment__status=PaymentStatusChoices.COMPLETED,
		verification_status=VerificationStatus.VERIFIED,
	)
	if organisation_ids is not None:
		if not organisation_ids:
			donation_total = Donation.objects.none()
		else:
			donation_total = donation_total.filter(payment__event__organisation_id__in=organisation_ids)
	if date_from:
		donation_total = donation_total.filter(donated_at__date__gte=date_from)
	if date_to:
		donation_total = donation_total.filter(donated_at__date__lte=date_to)

	verified_donation_amount = donation_total.aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
	total_revenue = round(sum(row["amount"] for row in sources), 2)

	events_count = _base_events_queryset(organisation_ids).count()
	average_event_revenue = round(total_revenue / events_count, 2) if events_count else 0.0

	return {
		"total_completed_payments": payments_qs.count(),
		"total_revenue": total_revenue,
		"average_payment_value": (
			round(total_revenue / payments_qs.count(), 2)
			if payments_qs.count()
			else 0.0
		),
		"average_event_revenue": average_event_revenue,
		"sources": sources,
		"verified_donations": {
			"count": donation_total.count(),
			"amount": float(verified_donation_amount),
		},
	}
