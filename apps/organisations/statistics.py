"""
Organisation Statistics Calculation Module

Provides organisation-focused analytics for admin dashboards.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Avg, Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.attendee.models import Attendee
from apps.bookings.models import Booking
from apps.common.models.verification import VerificationStatus
from apps.events.models import Event, EventStatusChoices
from apps.locations.models import AreaLocation, ChapterLocation, ClusterLocation, CountryLocation
from apps.organisations.models import (
	EventSponsor,
	EventSponsorPackage,
	Leader,
	Organisation,
	OrganisationControl,
	EventSponsorInvite,
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


def _base_sponsors_queryset(
	organisation_ids: list[int] | None,
	event_id=None,
	date_from=None,
	date_to=None,
):
	queryset = EventSponsor.objects.filter(event__deleted_at__isnull=True)
	if organisation_ids is not None:
		if not organisation_ids:
			return EventSponsor.objects.none()
		queryset = queryset.filter(organisation_id__in=organisation_ids)
	if event_id:
		queryset = queryset.filter(event__event_id=event_id)
	if date_from:
		queryset = queryset.filter(added_at__date__gte=date_from)
	if date_to:
		queryset = queryset.filter(added_at__date__lte=date_to)
	return queryset


def _base_sponsor_invites_queryset(
	organisation_ids: list[int] | None,
	event_id=None,
	date_from=None,
	date_to=None,
):
	queryset = EventSponsorInvite.objects.filter(event__deleted_at__isnull=True)
	if organisation_ids is not None:
		if not organisation_ids:
			return EventSponsorInvite.objects.none()
		queryset = queryset.filter(event__organisation_id__in=organisation_ids)
	if event_id:
		queryset = queryset.filter(event__event_id=event_id)
	if date_from:
		queryset = queryset.filter(sent_at__date__gte=date_from)
	if date_to:
		queryset = queryset.filter(sent_at__date__lte=date_to)
	return queryset


def _base_sponsor_payments_queryset(
	organisation_ids: list[int] | None,
	event_id=None,
	date_from=None,
	date_to=None,
):
	sponsor_type = ContentType.objects.get_for_model(EventSponsor)
	queryset = Payment.objects.filter(
		event__deleted_at__isnull=True,
		target_type=sponsor_type,
	)
	if organisation_ids is not None:
		if not organisation_ids:
			return Payment.objects.none()
		queryset = queryset.filter(event__organisation_id__in=organisation_ids)
	if event_id:
		queryset = queryset.filter(event__event_id=event_id)
	if date_from:
		queryset = queryset.filter(created_at__date__gte=date_from)
	if date_to:
		queryset = queryset.filter(created_at__date__lte=date_to)
	return queryset


def _base_inbound_sponsors_queryset(
	organisation_ids: list[int] | None,
	event_id=None,
	date_from=None,
	date_to=None,
):
	queryset = EventSponsor.objects.filter(event__deleted_at__isnull=True)
	if organisation_ids is not None:
		if not organisation_ids:
			return EventSponsor.objects.none()
		queryset = queryset.filter(event__organisation_id__in=organisation_ids)
	if event_id:
		queryset = queryset.filter(event__event_id=event_id)
	if date_from:
		queryset = queryset.filter(added_at__date__gte=date_from)
	if date_to:
		queryset = queryset.filter(added_at__date__lte=date_to)
	return queryset


def _base_outbound_sponsor_payments_queryset(
	organisation_ids: list[int] | None,
	event_id=None,
	date_from=None,
	date_to=None,
):
	sponsor_type = ContentType.objects.get_for_model(EventSponsor)
	sponsor_ids_qs = _base_sponsors_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	).values_list("id", flat=True)
	sponsor_ids = list(sponsor_ids_qs)
	if not sponsor_ids:
		return Payment.objects.none()

	queryset = Payment.objects.filter(
		event__deleted_at__isnull=True,
		target_type=sponsor_type,
		target_id__in=[str(sponsor_id) for sponsor_id in sponsor_ids],
	)
	if event_id:
		queryset = queryset.filter(event__event_id=event_id)
	if date_from:
		queryset = queryset.filter(created_at__date__gte=date_from)
	if date_to:
		queryset = queryset.filter(created_at__date__lte=date_to)
	return queryset


def _money_to_float(value) -> float:
	if value is None:
		return 0.0
	if hasattr(value, "amount"):
		return float(value.amount)
	return float(value)


def _get_revenue_sources(payments_queryset):
	booking_type = ContentType.objects.get_for_model(Booking)
	donation_type = ContentType.objects.get_for_model(Donation)
	sponsor_package_type = ContentType.objects.get_for_model(EventSponsor)

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

	def get_location_distribution(location_model, model_name_str):
		def _get_location_title(location):
			title = getattr(location, "title", None)
			if callable(title):
				return title()
			if isinstance(title, str):
				return title
			return str(location)

		location_rows = leaders_qs.filter(target_type=ContentType.objects.get_for_model(location_model)).values("target_id").annotate(
			value=Count("id")
		).order_by("-value")
		location_ids = [int(row["target_id"]) for row in location_rows if str(row["target_id"]).isdigit()]
		location_names = {
			loc.id: _get_location_title(loc)
			for loc in location_model.objects.filter(id__in=location_ids)
		}
		location_distribution = []
		for row in location_rows:
			target_id = row["target_id"]
			location_id = int(target_id) if str(target_id).isdigit() else None
			location_distribution.append(
				{
					"location_id": target_id,
					"label": location_names.get(location_id, f"Location #{target_id}"),
					"value": row["value"],
				}
			)
		return location_distribution

	area_distribution = get_location_distribution(AreaLocation, "arealocation")
	chapter_distribution = get_location_distribution(ChapterLocation, "chapterlocation")
	cluster_distribution = get_location_distribution(ClusterLocation, "clusterlocation")
	country_distribution = get_location_distribution(CountryLocation, "countrylocation")

	return {
		"total_leaders": total,
		"distribution": distribution,
		"area_distribution": area_distribution,
		"chapter_distribution": chapter_distribution,
		"cluster_distribution": cluster_distribution,
		"country_distribution": country_distribution,
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

	completed_payments_by_event = Payment.objects.filter(
		event_id=OuterRef("pk"),
		status=PaymentStatusChoices.COMPLETED,
	).values("event_id").annotate(
		total_count=Count("id"),
		total_amount=Coalesce(Sum("base_amount"), Decimal("0.00")),
	)

	annotated = events_qs.annotate(
		attendee_count=Count("attendees", filter=Q(attendees__deleted_at__isnull=True), distinct=True),
		completed_payment_count=Coalesce(
			Subquery(
				completed_payments_by_event.values("total_count")[:1],
				output_field=IntegerField(),
			),
			Value(0),
		),
		completed_payment_amount=Coalesce(
			Subquery(
				completed_payments_by_event.values("total_amount")[:1],
				output_field=DecimalField(max_digits=18, decimal_places=2),
			),
			Value(Decimal("0.00")),
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


def calculate_sponsor_overview_statistics(
	organisation_ids: list[int] | None = None,
	event_id=None,
	date_from=None,
	date_to=None,
) -> dict[str, Any]:
	sponsors_qs = _base_sponsors_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)
	invites_qs = _base_sponsor_invites_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)
	payments_qs = _base_sponsor_payments_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)

	total_sponsors = sponsors_qs.count()
	verification_counts = sponsors_qs.aggregate(
		pending=Count("id", filter=Q(verification_status=VerificationStatus.PENDING)),
		verified=Count("id", filter=Q(verification_status=VerificationStatus.VERIFIED)),
		rejected=Count("id", filter=Q(verification_status=VerificationStatus.REJECTED)),
		processed=Count("id", filter=Q(verification_status=VerificationStatus.PROCESSED)),
	)

	payment_counts = payments_qs.aggregate(
		total=Count("id"),
		completed=Count("id", filter=Q(status=PaymentStatusChoices.COMPLETED)),
		pending=Count("id", filter=Q(status=PaymentStatusChoices.PENDING)),
		failed=Count("id", filter=Q(status=PaymentStatusChoices.FAILED)),
		cancelled=Count("id", filter=Q(status=PaymentStatusChoices.CANCELLED)),
		completed_amount=Coalesce(Sum("base_amount", filter=Q(status=PaymentStatusChoices.COMPLETED)), Decimal("0.00")),
		pending_amount=Coalesce(Sum("base_amount", filter=Q(status=PaymentStatusChoices.PENDING)), Decimal("0.00")),
	)

	commitment_amount = 0.0
	for sponsor in sponsors_qs.select_related("package"):
		if sponsor.package_id:
			commitment_amount += _money_to_float(sponsor.package.modified_amount)

	total_invites = invites_qs.count()
	accepted_invites = invites_qs.filter(accepted=True).count()
	declined_invites = invites_qs.filter(declined=True).count()
	pending_invites = invites_qs.filter(accepted=False, declined=False).count()

	event_breakdown_qs = sponsors_qs.values("event__event_id", "event__title").annotate(
		sponsors=Count("id"),
		organisations=Count("organisation_id", distinct=True),
	).order_by("-sponsors")
	event_completed_revenue = {
		row["event__event_id"]: _money_to_float(row["amount"])
		for row in payments_qs.filter(status=PaymentStatusChoices.COMPLETED)
		.values("event__event_id")
		.annotate(amount=Coalesce(Sum("base_amount"), Decimal("0.00")))
	}
	event_breakdown = []
	for row in event_breakdown_qs:
		event_breakdown.append(
			{
				"event_id": str(row["event__event_id"]),
				"event_title": row["event__title"],
				"sponsors": row["sponsors"],
				"organisations": row["organisations"],
				"completed_revenue": round(event_completed_revenue.get(row["event__event_id"], 0.0), 2),
			}
		)

	completed_revenue = _money_to_float(payment_counts["completed_amount"])

	return {
		"total_sponsors": total_sponsors,
		"unique_organisations_sponsoring": sponsors_qs.values("organisation_id").distinct().count(),
		"verification_summary": {
			"pending": verification_counts["pending"],
			"verified": verification_counts["verified"],
			"rejected": verification_counts["rejected"],
			"processed": verification_counts["processed"],
		},
		"payment_summary": {
			"total": payment_counts["total"],
			"completed": payment_counts["completed"],
			"pending": payment_counts["pending"],
			"failed": payment_counts["failed"],
			"cancelled": payment_counts["cancelled"],
			"completed_revenue": round(completed_revenue, 2),
			"pending_revenue": round(_money_to_float(payment_counts["pending_amount"]), 2),
		},
		"invite_summary": {
			"total_sent": total_invites,
			"accepted": accepted_invites,
			"declined": declined_invites,
			"pending": pending_invites,
			"acceptance_rate": round((accepted_invites / total_invites) * 100, 2) if total_invites else 0.0,
			"response_rate": round(((accepted_invites + declined_invites) / total_invites) * 100, 2)
			if total_invites
			else 0.0,
		},
		"commitment_amount": round(commitment_amount, 2),
		"realization_rate": round((completed_revenue / commitment_amount) * 100, 2) if commitment_amount else 0.0,
		"event_breakdown": event_breakdown,
	}


def calculate_sponsor_package_performance_statistics(
	organisation_ids: list[int] | None = None,
	event_id=None,
	date_from=None,
	date_to=None,
	limit: int = 20,
) -> dict[str, Any]:
	sponsors_qs = _base_sponsors_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	).filter(package_id__isnull=False).select_related("package", "event")
	payments_qs = _base_sponsor_payments_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)

	package_metrics: dict[int, dict[str, Any]] = {}
	sponsor_package_by_id: dict[int, int] = {}
	for sponsor in sponsors_qs:
		if not sponsor.package_id:
			continue
		sponsor_package_by_id[sponsor.id] = sponsor.package_id
		if sponsor.package_id not in package_metrics:
			package_metrics[sponsor.package_id] = {
				"package_id": str(sponsor.package.package_id),
				"package_name": sponsor.package.package_name,
				"tier": sponsor.package.tier,
				"event_id": str(sponsor.event.event_id),
				"event_title": sponsor.event.title,
				"sponsor_count": 0,
				"organisation_ids": set(),
				"committed_revenue": 0.0,
				"completed_payment_count": 0,
				"completed_revenue": 0.0,
			}

		entry = package_metrics[sponsor.package_id]
		entry["sponsor_count"] += 1
		entry["organisation_ids"].add(sponsor.organisation_id)
		entry["committed_revenue"] += _money_to_float(sponsor.package.modified_amount)

	for payment in payments_qs.filter(status=PaymentStatusChoices.COMPLETED):
		try:
			sponsor_id = int(payment.target_id)
		except (TypeError, ValueError):
			continue
		package_pk = sponsor_package_by_id.get(sponsor_id)
		if not package_pk:
			continue
		entry = package_metrics[package_pk]
		entry["completed_payment_count"] += 1
		entry["completed_revenue"] += _money_to_float(payment.base_amount)

	rows = []
	for value in package_metrics.values():
		sponsor_count = value["sponsor_count"]
		rows.append(
			{
				"package_id": value["package_id"],
				"package_name": value["package_name"],
				"tier": value["tier"],
				"event_id": value["event_id"],
				"event_title": value["event_title"],
				"sponsor_count": sponsor_count,
				"organisation_count": len(value["organisation_ids"]),
				"committed_revenue": round(value["committed_revenue"], 2),
				"completed_payment_count": value["completed_payment_count"],
				"completed_revenue": round(value["completed_revenue"], 2),
				"realization_rate": round((value["completed_revenue"] / value["committed_revenue"]) * 100, 2)
				if value["committed_revenue"]
				else 0.0,
				"payment_success_rate": round((value["completed_payment_count"] / sponsor_count) * 100, 2)
				if sponsor_count
				else 0.0,
			}
		)

	rows.sort(key=lambda item: (item["completed_revenue"], item["sponsor_count"]), reverse=True)
	rows = rows[:limit]

	return {
		"packages": rows,
		"totals": {
			"total_packages": len(package_metrics),
			"total_sponsors": sum(item["sponsor_count"] for item in rows),
			"total_committed_revenue": round(sum(item["committed_revenue"] for item in rows), 2),
			"total_completed_revenue": round(sum(item["completed_revenue"] for item in rows), 2),
		},
		"limit": limit,
	}


def calculate_sponsor_invite_conversion_statistics(
	organisation_ids: list[int] | None = None,
	event_id=None,
	date_from=None,
	date_to=None,
) -> dict[str, Any]:
	invites_qs = _base_sponsor_invites_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)

	total_sent = invites_qs.count()
	accepted = invites_qs.filter(accepted=True).count()
	declined = invites_qs.filter(declined=True).count()
	pending = invites_qs.filter(accepted=False, declined=False).count()

	accepted_with_org = invites_qs.filter(accepted=True).exclude(organisation_id__isnull=True)
	accepted_org_ids = set(accepted_with_org.values_list("organisation_id", flat=True))
	accepted_event_ids = set(accepted_with_org.values_list("event_id", flat=True))

	matching_sponsors = EventSponsor.objects.filter(
		organisation_id__in=accepted_org_ids,
		event_id__in=accepted_event_ids,
		event__deleted_at__isnull=True,
	)
	if organisation_ids is not None:
		if not organisation_ids:
			matching_sponsors = EventSponsor.objects.none()
		else:
			matching_sponsors = matching_sponsors.filter(organisation_id__in=organisation_ids)
	if event_id:
		matching_sponsors = matching_sponsors.filter(event__event_id=event_id)

	event_rows = invites_qs.values("event__event_id", "event__title").annotate(
		total_sent=Count("id"),
		accepted_count=Count("id", filter=Q(accepted=True)),
		declined_count=Count("id", filter=Q(declined=True)),
		pending_count=Count("id", filter=Q(accepted=False, declined=False)),
	).order_by("-total_sent")

	event_breakdown = []
	for row in event_rows:
		total_for_event = row["total_sent"]
		event_breakdown.append(
			{
				"event_id": str(row["event__event_id"]),
				"event_title": row["event__title"],
				"total_sent": total_for_event,
				"accepted": row["accepted_count"],
				"declined": row["declined_count"],
				"pending": row["pending_count"],
				"acceptance_rate": round((row["accepted_count"] / total_for_event) * 100, 2)
				if total_for_event
				else 0.0,
			}
		)

	return {
		"summary": {
			"total_sent": total_sent,
			"accepted": accepted,
			"declined": declined,
			"pending": pending,
			"acceptance_rate": round((accepted / total_sent) * 100, 2) if total_sent else 0.0,
			"response_rate": round(((accepted + declined) / total_sent) * 100, 2) if total_sent else 0.0,
			"accepted_with_resulting_sponsor": matching_sponsors.count(),
		},
		"event_breakdown": event_breakdown,
	}


def calculate_sponsor_flow_statistics(
	organisation_ids: list[int] | None = None,
	event_id=None,
	date_from=None,
	date_to=None,
) -> dict[str, Any]:
	inbound_sponsors_qs = _base_inbound_sponsors_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	).select_related("organisation", "event", "package")

	outbound_sponsors_qs = _base_sponsors_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	).select_related("organisation", "event", "package")

	inbound_payments_qs = _base_sponsor_payments_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)
	outbound_payments_qs = _base_outbound_sponsor_payments_queryset(
		organisation_ids,
		event_id=event_id,
		date_from=date_from,
		date_to=date_to,
	)

	def build_summary(sponsors_qs, payments_qs):
		total_sponsors = sponsors_qs.count()
		unique_orgs = sponsors_qs.values("organisation_id").distinct().count()
		commitment_amount = 0.0
		for sponsor in sponsors_qs:
			if sponsor.package_id:
				commitment_amount += _money_to_float(sponsor.package.modified_amount)

		payment_counts = payments_qs.aggregate(
			total=Count("id"),
			completed=Count("id", filter=Q(status=PaymentStatusChoices.COMPLETED)),
			pending=Count("id", filter=Q(status=PaymentStatusChoices.PENDING)),
			failed=Count("id", filter=Q(status=PaymentStatusChoices.FAILED)),
			cancelled=Count("id", filter=Q(status=PaymentStatusChoices.CANCELLED)),
			completed_amount=Coalesce(
				Sum("base_amount", filter=Q(status=PaymentStatusChoices.COMPLETED)),
				Decimal("0.00"),
			),
			pending_amount=Coalesce(
				Sum("base_amount", filter=Q(status=PaymentStatusChoices.PENDING)),
				Decimal("0.00"),
			),
		)

		completed_revenue = _money_to_float(payment_counts["completed_amount"])
		pending_revenue = _money_to_float(payment_counts["pending_amount"])
		average_commitment = round(commitment_amount / total_sponsors, 2) if total_sponsors else 0.0
		average_completed = round(completed_revenue / total_sponsors, 2) if total_sponsors else 0.0

		return {
			"total_sponsors": total_sponsors,
			"unique_organisations": unique_orgs,
			"commitment_amount": round(commitment_amount, 2),
			"completed_revenue": round(completed_revenue, 2),
			"pending_revenue": round(pending_revenue, 2),
			"average_commitment_per_sponsor": average_commitment,
			"average_completed_revenue_per_sponsor": average_completed,
			"total_payments": payment_counts["total"],
			"completed_payments": payment_counts["completed"],
			"pending_payments": payment_counts["pending"],
			"failed_payments": payment_counts["failed"],
			"cancelled_payments": payment_counts["cancelled"],
		}

	def build_event_breakdown(sponsors_qs, payments_qs):
		rows: dict[str, dict[str, Any]] = {}
		for sponsor in sponsors_qs:
			event_id_value = str(sponsor.event.event_id)
			entry = rows.get(event_id_value)
			if not entry:
				entry = {
					"event_id": event_id_value,
					"event_title": sponsor.event.title,
					"sponsor_count": 0,
					"committed_amount": 0.0,
					"completed_revenue": 0.0,
				}
				rows[event_id_value] = entry

			entry["sponsor_count"] += 1
			if sponsor.package_id:
				entry["committed_amount"] += _money_to_float(sponsor.package.modified_amount)

		completed_rows = payments_qs.filter(status=PaymentStatusChoices.COMPLETED).values(
			"event__event_id",
			"event__title",
		).annotate(amount=Coalesce(Sum("base_amount"), Decimal("0.00")))
		for row in completed_rows:
			event_key = str(row["event__event_id"])
			entry = rows.get(event_key)
			if not entry:
				entry = {
					"event_id": event_key,
					"event_title": row["event__title"],
					"sponsor_count": 0,
					"committed_amount": 0.0,
					"completed_revenue": 0.0,
				}
				rows[event_key] = entry
			entry["completed_revenue"] += _money_to_float(row["amount"])

		return sorted(rows.values(), key=lambda item: item["sponsor_count"], reverse=True)

	def build_inbound_sponsor_breakdown(sponsors_qs):
		rows: dict[int, dict[str, Any]] = {}
		for sponsor in sponsors_qs:
			org_id = sponsor.organisation_id
			entry = rows.get(org_id)
			if not entry:
				entry = {
					"organisation_id": org_id,
					"organisation_title": sponsor.organisation.title,
					"sponsor_count": 0,
					"committed_amount": 0.0,
				}
				rows[org_id] = entry
			entry["sponsor_count"] += 1
			if sponsor.package_id:
				entry["committed_amount"] += _money_to_float(sponsor.package.modified_amount)

		return sorted(rows.values(), key=lambda item: item["committed_amount"], reverse=True)

	inbound_summary = build_summary(inbound_sponsors_qs, inbound_payments_qs)
	outbound_summary = build_summary(outbound_sponsors_qs, outbound_payments_qs)

	net_summary = {
		"sponsor_count_delta": inbound_summary["total_sponsors"] - outbound_summary["total_sponsors"],
		"commitment_amount_delta": round(
			inbound_summary["commitment_amount"] - outbound_summary["commitment_amount"],
			2,
		),
		"completed_revenue_delta": round(
			inbound_summary["completed_revenue"] - outbound_summary["completed_revenue"],
			2,
		),
		"average_commitment_per_sponsor_delta": round(
			inbound_summary["average_commitment_per_sponsor"]
			- outbound_summary["average_commitment_per_sponsor"],
			2,
		),
		"average_completed_revenue_per_sponsor_delta": round(
			inbound_summary["average_completed_revenue_per_sponsor"]
			- outbound_summary["average_completed_revenue_per_sponsor"],
			2,
		),
	}

	return {
		"inbound_summary": inbound_summary,
		"outbound_summary": outbound_summary,
		"net_summary": net_summary,
		"inbound_by_sponsor": build_inbound_sponsor_breakdown(inbound_sponsors_qs),
		"inbound_by_event": build_event_breakdown(inbound_sponsors_qs, inbound_payments_qs),
		"outbound_by_event": build_event_breakdown(outbound_sponsors_qs, outbound_payments_qs),
	}
