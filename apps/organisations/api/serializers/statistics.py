"""
Organisation Statistics Serializers.
"""
from typing import Any

from rest_framework import serializers

from apps.attendee import formatters


class BaseOrganisationStatisticsSerializer(serializers.Serializer):
	"""Base serializer supporting raw and ECharts response modes."""

	def to_representation(self, instance):
		representation = super().to_representation(instance)

		request = self.context.get("request")
		if request and request.query_params.get("format") == "echarts":
			return self.format_for_echarts(representation)

		return representation

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		return data


class OverviewStatisticsSerializer(BaseOrganisationStatisticsSerializer):
	total_organisations = serializers.IntegerField()
	total_events = serializers.IntegerField()
	active_events = serializers.IntegerField()
	upcoming_events = serializers.IntegerField()
	completed_events = serializers.IntegerField()
	total_attendees = serializers.IntegerField()
	average_attendees_per_event = serializers.FloatField()
	total_members = serializers.IntegerField()
	verified_members = serializers.IntegerField()
	total_controllers = serializers.IntegerField()
	total_revenue = serializers.FloatField()
	total_completed_payments = serializers.IntegerField()
	average_payment_value = serializers.FloatField()
	average_event_revenue = serializers.FloatField()
	revenue_sources = serializers.ListField(child=serializers.DictField())
	event_status_distribution = serializers.ListField(child=serializers.DictField())
	payment_status_distribution = serializers.ListField(child=serializers.DictField())
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		return {
			"summary": {
				"total_organisations": data["total_organisations"],
				"total_events": data["total_events"],
				"total_attendees": data["total_attendees"],
				"total_revenue": data["total_revenue"],
			},
			"event_status_chart": formatters.format_pie_chart(
				data=data["event_status_distribution"],
				title="Event Status Distribution",
			),
			"revenue_source_chart": formatters.format_donut_chart(
				data=[{"label": item["label"], "value": item["amount"]} for item in data["revenue_sources"]],
				title="Revenue Source Distribution",
			),
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationOverviewStatistics"


class LeaderDistributionSerializer(BaseOrganisationStatisticsSerializer):
	total_leaders = serializers.IntegerField()
	distribution = serializers.ListField(child=serializers.DictField())
	area_distribution = serializers.ListField(child=serializers.DictField())
	cluster_distribution = serializers.ListField(child=serializers.DictField())
	chapter_distribution = serializers.ListField(child=serializers.DictField())
	country_distribution = serializers.ListField(child=serializers.DictField())
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		return {
			"leader_location_chart": formatters.format_pie_chart(
				data=data["distribution"],
				title="Leaders by Location Type",
			),
			"area_leader_chart": formatters.format_bar_chart(
				data=[{"label": item["label"], "value": item["value"]} for item in data["area_distribution"]],
				title="Area Leader Distribution",
				x_axis_label="Area",
				y_axis_label="Leaders",
			),
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationLeaderDistributionStatistics"


class EventPerformanceSerializer(BaseOrganisationStatisticsSerializer):
	events = serializers.ListField(child=serializers.DictField())
	totals = serializers.DictField()
	limit = serializers.IntegerField()
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		return {
			"attendees_by_event_chart": formatters.format_bar_chart(
				data=[{"label": item["event_title"], "value": item["attendee_count"]} for item in data["events"]],
				title="Attendees per Event",
				x_axis_label="Event",
				y_axis_label="Attendees",
			),
			"payments_by_event_chart": formatters.format_bar_chart(
				data=[{"label": item["event_title"], "value": item["completed_payment_amount"]} for item in data["events"]],
				title="Completed Payment Value per Event",
				x_axis_label="Event",
				y_axis_label="Revenue",
			),
			"totals": data.get("totals", {}),
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationEventPerformanceStatistics"


class PaymentSourcesSerializer(BaseOrganisationStatisticsSerializer):
	total_completed_payments = serializers.IntegerField()
	total_revenue = serializers.FloatField()
	average_payment_value = serializers.FloatField()
	average_event_revenue = serializers.FloatField()
	sources = serializers.ListField(child=serializers.DictField())
	verified_donations = serializers.DictField()
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		return {
			"payment_source_count_chart": formatters.format_pie_chart(
				data=data["sources"],
				title="Completed Payments by Source",
			),
			"payment_source_revenue_chart": formatters.format_bar_chart(
				data=[{"label": item["label"], "value": item["amount"]} for item in data["sources"]],
				title="Revenue by Source",
				x_axis_label="Source",
				y_axis_label="Revenue",
			),
			"summary": {
				"total_revenue": data["total_revenue"],
				"average_payment_value": data["average_payment_value"],
				"average_event_revenue": data["average_event_revenue"],
			},
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationPaymentSourcesStatistics"


class SponsorOverviewStatisticsSerializer(BaseOrganisationStatisticsSerializer):
	total_sponsors = serializers.IntegerField()
	unique_organisations_sponsoring = serializers.IntegerField()
	verification_summary = serializers.DictField()
	payment_summary = serializers.DictField()
	invite_summary = serializers.DictField()
	commitment_amount = serializers.FloatField()
	realization_rate = serializers.FloatField()
	event_breakdown = serializers.ListField(child=serializers.DictField())
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		verification_summary = data.get("verification_summary", {})
		payment_summary = data.get("payment_summary", {})
		invite_summary = data.get("invite_summary", {})

		return {
			"verification_status_chart": formatters.format_pie_chart(
				data=[
					{"label": "Pending", "value": verification_summary.get("pending", 0)},
					{"label": "Verified", "value": verification_summary.get("verified", 0)},
					{"label": "Rejected", "value": verification_summary.get("rejected", 0)},
					{"label": "Processed", "value": verification_summary.get("processed", 0)},
				],
				title="Sponsor Verification Status",
			),
			"payment_status_chart": formatters.format_pie_chart(
				data=[
					{"label": "Completed", "value": payment_summary.get("completed", 0)},
					{"label": "Pending", "value": payment_summary.get("pending", 0)},
					{"label": "Failed", "value": payment_summary.get("failed", 0)},
					{"label": "Cancelled", "value": payment_summary.get("cancelled", 0)},
				],
				title="Sponsor Payment Status",
			),
			"event_revenue_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("event_title"), "value": item.get("completed_revenue", 0)}
					for item in data.get("event_breakdown", [])
				],
				title="Completed Sponsorship Revenue by Event",
				x_axis_label="Event",
				y_axis_label="Revenue",
			),
			"summary": {
				"total_sponsors": data.get("total_sponsors", 0),
				"commitment_amount": data.get("commitment_amount", 0.0),
				"completed_revenue": payment_summary.get("completed_revenue", 0.0),
				"realization_rate": data.get("realization_rate", 0.0),
				"invite_acceptance_rate": invite_summary.get("acceptance_rate", 0.0),
			},
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationSponsorOverviewStatistics"


class SponsorPackagePerformanceSerializer(BaseOrganisationStatisticsSerializer):
	packages = serializers.ListField(child=serializers.DictField())
	totals = serializers.DictField()
	limit = serializers.IntegerField()
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		return {
			"package_committed_revenue_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("package_name"), "value": item.get("committed_revenue", 0)}
					for item in data.get("packages", [])
				],
				title="Committed Sponsorship Revenue by Package",
				x_axis_label="Package",
				y_axis_label="Revenue",
			),
			"package_realized_revenue_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("package_name"), "value": item.get("completed_revenue", 0)}
					for item in data.get("packages", [])
				],
				title="Realized Sponsorship Revenue by Package",
				x_axis_label="Package",
				y_axis_label="Revenue",
			),
			"package_sponsor_count_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("package_name"), "value": item.get("sponsor_count", 0)}
					for item in data.get("packages", [])
				],
				title="Sponsors per Package",
				x_axis_label="Package",
				y_axis_label="Sponsors",
			),
			"totals": data.get("totals", {}),
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationSponsorPackagePerformanceStatistics"


class SponsorInviteConversionSerializer(BaseOrganisationStatisticsSerializer):
	summary = serializers.DictField()
	event_breakdown = serializers.ListField(child=serializers.DictField())
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		summary = data.get("summary", {})
		return {
			"invite_outcome_chart": formatters.format_pie_chart(
				data=[
					{"label": "Accepted", "value": summary.get("accepted", 0)},
					{"label": "Declined", "value": summary.get("declined", 0)},
					{"label": "Pending", "value": summary.get("pending", 0)},
				],
				title="Sponsor Invite Outcomes",
			),
			"event_acceptance_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("event_title"), "value": item.get("acceptance_rate", 0)}
					for item in data.get("event_breakdown", [])
				],
				title="Invite Acceptance Rate by Event",
				x_axis_label="Event",
				y_axis_label="Acceptance Rate (%)",
			),
			"summary": summary,
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationSponsorInviteConversionStatistics"


class SponsorFlowStatisticsSerializer(BaseOrganisationStatisticsSerializer):
	"""Inbound/outbound sponsorship flow statistics."""

	inbound_summary = serializers.DictField()
	outbound_summary = serializers.DictField()
	net_summary = serializers.DictField()
	inbound_by_sponsor = serializers.ListField(child=serializers.DictField())
	inbound_by_event = serializers.ListField(child=serializers.DictField())
	outbound_by_event = serializers.ListField(child=serializers.DictField())
	generated_at = serializers.DateTimeField()
	scope = serializers.DictField()
	filters_applied = serializers.DictField()

	def format_for_echarts(self, data: dict[str, Any]) -> dict[str, Any]:
		inbound_summary = data.get("inbound_summary", {})
		outbound_summary = data.get("outbound_summary", {})

		return {
			"summary": {
				"inbound": inbound_summary,
				"outbound": outbound_summary,
				"net": data.get("net_summary", {}),
			},
			"inbound_sponsors_chart": formatters.format_pie_chart(
				data=[
					{"label": item.get("organisation_title"), "value": item.get("committed_amount", 0)}
					for item in data.get("inbound_by_sponsor", [])
				],
				title="Inbound Sponsors by Organisation",
			),
			"inbound_event_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("event_title"), "value": item.get("sponsor_count", 0)}
					for item in data.get("inbound_by_event", [])
				],
				title="Inbound Sponsors by Event",
				x_axis_label="Event",
				y_axis_label="Sponsors",
			),
			"outbound_event_chart": formatters.format_bar_chart(
				data=[
					{"label": item.get("event_title"), "value": item.get("sponsor_count", 0)}
					for item in data.get("outbound_by_event", [])
				],
				title="Outbound Sponsors by Event",
				x_axis_label="Event",
				y_axis_label="Sponsors",
			),
			"inbound_outbound_revenue_chart": formatters.format_bar_chart(
				data=[
					{"label": "Inbound", "value": inbound_summary.get("completed_revenue", 0)},
					{"label": "Outbound", "value": outbound_summary.get("completed_revenue", 0)},
				],
				title="Inbound vs Outbound Completed Revenue",
				x_axis_label="Direction",
				y_axis_label="Revenue",
			),
			"scope": data.get("scope", {}),
			"filters_applied": data.get("filters_applied", {}),
			"generated_at": data.get("generated_at"),
		}

	class Meta:
		ref_name = "OrganisationSponsorFlowStatistics"
