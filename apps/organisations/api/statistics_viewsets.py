"""
Organisation Statistics API ViewSet.
"""
from datetime import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import exceptions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.organisations import statistics
from apps.organisations.api.serializers.statistics import (
	EventPerformanceSerializer,
	LeaderDistributionSerializer,
	OverviewStatisticsSerializer,
	PaymentSourcesSerializer,
)
from apps.organisations.models import Organisation, OrganisationControl


ORGANISATION_ID_PARAM = OpenApiParameter(
	name="organisation_id",
	type=OpenApiTypes.INT,
	location=OpenApiParameter.QUERY,
	description=(
		"Organisation id. Non-superusers can only access organisations they control. "
		"Superusers may request any organisation id."
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
		org_id_raw = request.query_params.get("organisation_id")

		if org_id_raw:
			try:
				org_id = int(org_id_raw)
			except ValueError as exc:
				raise exceptions.ValidationError({"organisation_id": "Must be an integer."}) from exc

			if request.user.is_superuser:
				if not Organisation.objects.filter(id=org_id).exists():
					raise exceptions.NotFound("Organisation not found.")
				return {
					"organisation_ids": [org_id],
					"scope_label": "single_organisation",
					"requested_organisation_id": org_id,
				}

			if not OrganisationControl.objects.filter(organisation_id=org_id, user=request.user).exists():
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

	def _build_filters_metadata(self, request):
		return {
			"organisation_id": request.query_params.get("organisation_id"),
			"date_from": request.query_params.get("date_from"),
			"date_to": request.query_params.get("date_to"),
			"format": request.query_params.get("format", "raw"),
			"limit": request.query_params.get("limit"),
		}

	def list(self, request):
		return Response(
			{
				"endpoints": {
					"overview": "Combined organisation overview statistics",
					"leaders-distribution": "Distribution of leaders over location types and areas",
					"event-performance": "Event counts, attendees, and payment totals/averages per event",
					"payments-by-source": "Completed payments split by bookings/donations/sponsorships",
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
		date_from = self._parse_iso_date(request.query_params.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.query_params.get("date_to"), "date_to")

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
		payload["generated_at"] = datetime.utcnow()
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
		date_from = self._parse_iso_date(request.query_params.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.query_params.get("date_to"), "date_to")

		try:
			limit = int(request.query_params.get("limit", 20))
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
		date_from = self._parse_iso_date(request.query_params.get("date_from"), "date_from")
		date_to = self._parse_iso_date(request.query_params.get("date_to"), "date_to")

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
