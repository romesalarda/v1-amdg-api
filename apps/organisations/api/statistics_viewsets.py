"""
Organisation Statistics API ViewSet.
"""
from datetime import datetime
from uuid import UUID

from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import exceptions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.organisations import statistics
from apps.organisations.api.serializers.statistics import (
	EventPerformanceSerializer,
	EventsOnMapSerializer,
	LeaderDistributionSerializer,
	LeadersOnMapSerializer,
	OverviewStatisticsSerializer,
	PaymentSourcesSerializer,
	SponsorInviteConversionSerializer,
	SponsorOverviewStatisticsSerializer,
	SponsorPackagePerformanceSerializer,
	SponsorFlowStatisticsSerializer,
)
from apps.events.models import Event
from apps.organisations.models import Leader, Organisation, OrganisationControl
from apps.utils.querying import get_event_or_url_safe_title, get_organisation_or_url_safe_title


ORGANISATION_ID_PARAM = OpenApiParameter(
	name="organisation_id",
	type=OpenApiTypes.STR,
	location=OpenApiParameter.QUERY,
	description=(
		"Organisation id or url_safe_title. Non-superusers can only access organisations they control. "
		"Superusers may request any organisation identifier."
	),
	required=False,
)

FORMAT_PARAM = OpenApiParameter(
	name="format",
	type=OpenApiTypes.STR,
	location=OpenApiParameter.QUERY,
	description="Response format. raw (default) or echarts.",
	required=False,
	enum=["raw", "echarts"],
	default="raw",
)

DATE_FROM_PARAM = OpenApiParameter(
	name="date_from",
	type=OpenApiTypes.DATE,
	location=OpenApiParameter.QUERY,
	description="Start date filter (YYYY-MM-DD).",
	required=False,
)

DATE_TO_PARAM = OpenApiParameter(
	name="date_to",
	type=OpenApiTypes.DATE,
	location=OpenApiParameter.QUERY,
	description="End date filter (YYYY-MM-DD).",
	required=False,
)

EVENT_ID_PARAM = OpenApiParameter(
	name="event_id",
	type=OpenApiTypes.UUID,
	location=OpenApiParameter.QUERY,
	description="Event public UUID filter.",
	required=False,
)

LIMIT_PARAM = OpenApiParameter(
	name="limit",
	type=OpenApiTypes.INT,
	location=OpenApiParameter.QUERY,
	description="Maximum events to return in event-performance endpoint.",
	required=False,
	default=20,
)
class OrganisationStatisticsViewSet(viewsets.GenericViewSet):
	"""Statistics endpoints for organisations, events, members and payments."""

	permission_classes = [IsAuthenticated]
	queryset = Organisation.objects.none()
	serializer_class = OverviewStatisticsSerializer

	def _parse_iso_date(self, value: str | None, field_name: str):
		if not value:
			return None
		try:
			return datetime.strptime(value, "%Y-%m-%d").date()
		except ValueError as exc:
			raise exceptions.ValidationError({field_name: "Invalid date format. Use YYYY-MM-DD."}) from exc

	def _get_scope(self, request):
		org_id_raw = request.GET.get("organisation_id")

		if org_id_raw:
			try:
				organisation = get_organisation_or_url_safe_title(org_id_raw)
			except Http404 as exc:
				raise exceptions.NotFound("Organisation not found.") from exc
			org_id = organisation.id

			if request.user.is_superuser:
				return {
					"organisation_ids": [org_id],
					"scope_label": "single_organisation",
					"requested_organisation_id": org_id,
				}

			if not OrganisationControl.objects.filter(organisation=organisation, user=request.user).exists():
				raise exceptions.PermissionDenied(
					"You can only access statistics for organisations you control."
				)
			return {
				"organisation_ids": [org_id],
				"scope_label": "single_organisation",
				"requested_organisation_id": org_id,
			}

		if request.user.is_superuser:
			return {
				"organisation_ids": None,
				"scope_label": "global",
				"requested_organisation_id": None,
			}

		controlled_ids = list(
			OrganisationControl.objects.filter(user=request.user).values_list("organisation_id", flat=True)
		)
		return {
			"organisation_ids": controlled_ids,
			"scope_label": "controlled_organisations",
			"requested_organisation_id": None,
		}

	def _parse_event_id(self, value: str | None, scope: dict[str, object]):
		if not value:
			return None

		try:
			UUID(value)
		except ValueError:
			value = str(get_event_or_url_safe_title(value).event_id)


		event = Event.objects.filter(event_id=value).first()
		if event is None:
			raise exceptions.NotFound("Event not found.")

		organisation_ids = scope.get("organisation_ids")
		if organisation_ids is not None and event.organisation_id not in organisation_ids:
			raise exceptions.PermissionDenied(
				"You can only access statistics for events in organisations you control."
			)
		return event.event_id

	def _build_filters_metadata(self, request):
		return {
			"organisation_id": request.GET.get("organisation_id"),
			"event_id": request.GET.get("event_id"),
			"date_from": request.GET.get("date_from"),
			"date_to": request.GET.get("date_to"),
			"format": request.GET.get("format", "raw"),
			"limit": request.GET.get("limit"),
		}

	def list(self, request):
		return Response(
			{
				"endpoints": {
					"overview": "Combined organisation overview statistics",
					"leaders-distribution": "Distribution of leaders over location types and areas",
					"event-performance": "Event counts, attendees, and payment totals/averages per event",
					"payments-by-source": "Completed payments split by bookings/donations/sponsorships",
					"sponsors-overview": "Sponsor pipeline, commitments, and realized payment metrics",
					"sponsor-packages-performance": "Per-package sponsor adoption and revenue realization",
					"sponsor-invite-conversion": "Sponsor invite acceptance and conversion analytics",
					"sponsors-flow": "Inbound vs outbound sponsorship flow statistics",
					"events-on-map": "Returns a GeoJSON FeatureCollection of events for a given organisation.",
					"leaders-on-map": "Returns a GeoJSON FeatureCollection of leaders for a given organisation.",
				}
			}
		)

	@extend_schema(
		summary="Organisation statistics overview",
		description="Dashboard overview for organisations, events, attendees, members and payments.",
		parameters=[ORGANISATION_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, FORMAT_PARAM],
		responses={200: OverviewStatisticsSerializer},
		tags=["Organisation Statistics"],
		examples=[
			OpenApiExample(
				"Overview Example",
				value={
					"total_organisations": 2,
					"total_events": 8,
					"total_attendees": 153,
					"total_members": 34,
					"total_revenue": 41250.0,
				},
				response_only=True,
			)
		],
	)
	@action(detail=False, methods=["get"], url_path="overview")
	def overview(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")

		payload = statistics.calculate_overview_statistics(
			organisation_ids=scope["organisation_ids"],
			date_from=date_from,
			date_to=date_to,
		)
		payload["generated_at"] = datetime.utcnow()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = OverviewStatisticsSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Leader distribution statistics",
		description="Shows distribution of organisation leaders by location type and detailed area distribution.",
		parameters=[ORGANISATION_ID_PARAM, FORMAT_PARAM],
		responses={200: LeaderDistributionSerializer},
		tags=["Organisation Statistics"],
	)
	@action(detail=False, methods=["get"], url_path="leaders-distribution")
	def leaders_distribution(self, request):
		scope = self._get_scope(request)
		payload = statistics.calculate_leader_distribution(organisation_ids=scope["organisation_ids"])
		payload["generated_at"] = datetime.now()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)
		serializer = LeaderDistributionSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Event performance statistics",
		description="Per-event attendee counts and payment totals/averages for organisation-scoped events.",
		parameters=[ORGANISATION_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, LIMIT_PARAM, FORMAT_PARAM],
		responses={200: EventPerformanceSerializer},
		tags=["Organisation Statistics"],
	)
	@action(detail=False, methods=["get"], url_path="event-performance")
	def event_performance(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")

		try:
			limit = int(request.GET.get("limit", 20))
		except ValueError as exc:
			raise exceptions.ValidationError({"limit": "Must be an integer."}) from exc
		if limit < 1:
			raise exceptions.ValidationError({"limit": "Must be greater than zero."})

		payload = statistics.calculate_event_performance_statistics(
			organisation_ids=scope["organisation_ids"],
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		)
		payload["generated_at"] = datetime.utcnow()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = EventPerformanceSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Payments by source statistics",
		description="Completed payments split into booking, donation, sponsorship and other sources.",
		parameters=[ORGANISATION_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, FORMAT_PARAM],
		responses={200: PaymentSourcesSerializer},
		tags=["Organisation Statistics"],
	)
	@action(detail=False, methods=["get"], url_path="payments-by-source")
	def payments_by_source(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")

		payload = statistics.calculate_payments_by_source_statistics(
			organisation_ids=scope["organisation_ids"],
			date_from=date_from,
			date_to=date_to,
		)
		payload["generated_at"] = datetime.utcnow()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = PaymentSourcesSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Sponsor overview statistics",
		description="Sponsor KPI overview with verification, payment, invite and event-level breakdowns.",
		parameters=[ORGANISATION_ID_PARAM, EVENT_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, FORMAT_PARAM],
		responses={200: SponsorOverviewStatisticsSerializer},
		tags=["Sponsor Statistics"],
		examples=[
			OpenApiExample(
				"Sponsor Overview Example",
				value={
					"total_sponsors": 8,
					"unique_organisations_sponsoring": 5,
					"verification_summary": {"pending": 2, "verified": 4, "rejected": 1, "processed": 1},
					"payment_summary": {"total": 7, "completed": 5, "pending": 1, "failed": 1, "cancelled": 0, "completed_revenue": 5250.0, "pending_revenue": 500.0},
					"invite_summary": {"total_sent": 10, "accepted": 5, "declined": 2, "pending": 3, "acceptance_rate": 50.0, "response_rate": 70.0},
					"commitment_amount": 6000.0,
					"realization_rate": 87.5,
				},
				response_only=True,
			)
		],
	)
	@action(detail=False, methods=["get"], url_path="sponsors-overview")
	def sponsors_overview(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")
		event_id = self._parse_event_id(request.GET.get("event_id"), scope)

		payload = statistics.calculate_sponsor_overview_statistics(
			organisation_ids=scope["organisation_ids"],
			event_id=event_id,
			date_from=date_from,
			date_to=date_to,
		)
		payload["generated_at"] = datetime.utcnow()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = SponsorOverviewStatisticsSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Sponsor package performance statistics",
		description="Package-level sponsor counts, committed revenue, completed revenue and realization rates.",
		parameters=[ORGANISATION_ID_PARAM, EVENT_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, LIMIT_PARAM, FORMAT_PARAM],
		responses={200: SponsorPackagePerformanceSerializer},
		tags=["Sponsor Statistics"],
		examples=[
			OpenApiExample(
				"Sponsor Package Performance Example",
				value={
					"packages": [
						{
							"package_name": "Gold",
							"sponsor_count": 3,
							"committed_revenue": 3000.0,
							"completed_revenue": 2500.0,
							"realization_rate": 83.33,
						}
					],
					"totals": {"total_packages": 1, "total_sponsors": 3, "total_committed_revenue": 3000.0, "total_completed_revenue": 2500.0},
					"limit": 20,
				},
				response_only=True,
			)
		],
	)
	@action(detail=False, methods=["get"], url_path="sponsor-packages-performance")
	def sponsor_packages_performance(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")
		event_id = self._parse_event_id(request.GET.get("event_id"), scope)

		try:
			limit = int(request.GET.get("limit", 20))
		except ValueError as exc:
			raise exceptions.ValidationError({"limit": "Must be an integer."}) from exc
		if limit < 1:
			raise exceptions.ValidationError({"limit": "Must be greater than zero."})

		payload = statistics.calculate_sponsor_package_performance_statistics(
			organisation_ids=scope["organisation_ids"],
			event_id=event_id,
			date_from=date_from,
			date_to=date_to,
			limit=limit,
		)
		payload["generated_at"] = datetime.utcnow()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = SponsorPackagePerformanceSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Sponsor invite conversion statistics",
		description="Invite outcomes and conversion from accepted invites to actual sponsors.",
		parameters=[ORGANISATION_ID_PARAM, EVENT_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, FORMAT_PARAM],
		responses={200: SponsorInviteConversionSerializer},
		tags=["Sponsor Statistics"],
		examples=[
			OpenApiExample(
				"Sponsor Invite Conversion Example",
				value={
					"summary": {
						"total_sent": 12,
						"accepted": 6,
						"declined": 3,
						"pending": 3,
						"acceptance_rate": 50.0,
						"response_rate": 75.0,
						"accepted_with_resulting_sponsor": 5,
					},
				},
				response_only=True,
			)
		],
	)
	@action(detail=False, methods=["get"], url_path="sponsor-invite-conversion")
	def sponsor_invite_conversion(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")
		event_id = self._parse_event_id(request.GET.get("event_id"), scope)

		payload = statistics.calculate_sponsor_invite_conversion_statistics(
			organisation_ids=scope["organisation_ids"],
			event_id=event_id,
			date_from=date_from,
			date_to=date_to,
		)
		payload["generated_at"] = datetime.now()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = SponsorInviteConversionSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Sponsor flow statistics",
		description=(
			"Inbound vs outbound sponsorship metrics with organisation and event breakdowns."
		),
		parameters=[ORGANISATION_ID_PARAM, EVENT_ID_PARAM, DATE_FROM_PARAM, DATE_TO_PARAM, FORMAT_PARAM],
		responses={200: SponsorFlowStatisticsSerializer},
		tags=["Sponsor Statistics"],
	)
	@action(detail=False, methods=["get"], url_path="sponsors-flow")
	def sponsors_flow(self, request):
		scope = self._get_scope(request)
		date_from = self._parse_iso_date(request.GET.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.GET.get("date_to"), "date_to")
		event_id = self._parse_event_id(request.GET.get("event_id"), scope)

		payload = statistics.calculate_sponsor_flow_statistics(
			organisation_ids=scope["organisation_ids"],
			event_id=event_id,
			date_from=date_from,
			date_to=date_to,
		)
		payload["generated_at"] = datetime.utcnow()
		payload["scope"] = {
			"type": scope["scope_label"],
			"organisation_ids": scope["organisation_ids"],
		}
		payload["filters_applied"] = self._build_filters_metadata(request)

		serializer = SponsorFlowStatisticsSerializer(payload, context={"request": request})
		return Response(serializer.data)

	@extend_schema(
		summary="Events on Map",
		description="Returns a GeoJSON FeatureCollection of events for a given organisation.",
		parameters=[ORGANISATION_ID_PARAM],
		responses={200: EventsOnMapSerializer},
		tags=["Organisation Statistics"],
	)
	@action(detail=False, methods=["get"], url_path="events-on-map")
	def events_on_map(self, request):
		scope = self._get_scope(request)
		organisation_ids = scope["organisation_ids"]

		events = Event.objects.filter(
			event_venues__latitude__isnull=False,
			event_venues__longitude__isnull=False,
		).distinct()
		if organisation_ids is not None:
			events = events.filter(organisation_id__in=organisation_ids)

		features = []
		for event in events.prefetch_related("event_venues", "attendees"):
			event_venue = event.event_venues.filter(
				latitude__isnull=False,
				longitude__isnull=False,
			).first()
			if event_venue:
				features.append({
					"type": "Feature",
					"geometry": {
						"type": "Point",
						"coordinates": [
							float(event_venue.longitude),
							float(event_venue.latitude),
						]
					},
					"properties": {
						"event_id": str(event.event_id),
						"name": event.title,
						"start_date": event.start_datetime.isoformat(),
						"attendee_count": event.attendees.count(),
					}
				})

		feature_collection = {
			"type": "FeatureCollection",
			"features": features
		}

		return Response(feature_collection)

	@extend_schema(
		summary="Leaders on Map",
		description="Returns a GeoJSON FeatureCollection of leaders for a given organisation.",
		parameters=[ORGANISATION_ID_PARAM],
		responses={200: LeadersOnMapSerializer},
		tags=["Organisation Statistics"],
	)
	@action(detail=False, methods=["get"], url_path="leaders-on-map")
	def leaders_on_map(self, request):
		scope = self._get_scope(request)
		organisation_ids = scope["organisation_ids"]

		leaders = Leader.objects.select_related("user", "organisation", "target_type").all()
		if organisation_ids is not None:
			leaders = leaders.filter(organisation_id__in=organisation_ids)

		features = []
		for leader in leaders:
			location = leader.authority_object
			if location is None:
				continue
			latitude = getattr(location, "latitude", None)
			longitude = getattr(location, "longitude", None)
			if latitude is None or longitude is None:
				continue
			features.append({
				"type": "Feature",
				"geometry": {
					"type": "Point",
					"coordinates": [float(longitude), float(latitude)],
				},
				"properties": {
					"name": leader.user.get_full_name() or leader.user.username,
					"role": leader.location_type or "Leader",
					"location_name": leader.location_name,
				}
			})

		feature_collection = {
			"type": "FeatureCollection",
			"features": features
		}

		return Response(feature_collection)
