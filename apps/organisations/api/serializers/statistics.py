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
