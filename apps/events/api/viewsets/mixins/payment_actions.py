"""
EventPaymentActionsMixin — user-facing payment/booking actions for EventViewSet.
"""
from __future__ import annotations

import uuid

from django.db.models import Q
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.bookings.models import Booking
from apps.events.api.serializers import (
    EventMyBookingResponseSerializer,
    EventMyOutstandingPaymentSerializer,
    EventMyPaymentSummarySerializer,
)
from apps.events.api.filtersets import (
    EventMyBookingFilterSet,
    EventMyOutstandingPaymentsFilterSet,
)
from apps.events.api.pagination import StandardPagination
from apps.events.services import OutstandingPaymentsService
from apps.events.services.payment_summary import EventPaymentSummaryService


class EventPaymentActionsMixin:
    """Mixin providing payment/booking summary @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # my_booking
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get Current User Bookings For Event (Paginated)",
        description=(
            "Retrieve all of the current authenticated user's bookings for this event with "
            "pagination and filtering support. Results include attendees, tickets, and payments."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name="has_outstanding_payments", type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booked_after", type=OpenApiTypes.DATETIME, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booked_before", type=OpenApiTypes.DATETIME, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booked_in_days", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="attendee_name", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booking_reference", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="page", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY),
        ],
        responses={
            200: OpenApiResponse(description="Paginated list of user bookings"),
            401: OpenApiResponse(description="Authentication required"),
            404: OpenApiResponse(description="Event not found"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="my-booking",
        permission_classes=[permissions.IsAuthenticated],
    )
    def my_booking(self, request, *args, **kwargs):
        event = self.get_object()

        base_queryset = (
            Booking.objects.filter(event=event)
            .filter(Q(made_by=request.user) | Q(attendees__user=request.user))
            .select_related("event", "made_by")
            .prefetch_related("attendees__tickets", "attendees__user")
            .distinct()
            .order_by("-booked_at", "-id")
        )

        filterset = EventMyBookingFilterSet(
            request.GET, queryset=base_queryset, request=request
        )
        filtered_queryset = filterset.qs

        paginator = StandardPagination()
        paginated_queryset = paginator.paginate_queryset(filtered_queryset, request)
        if paginated_queryset is None:
            paginated_queryset = filtered_queryset

        booking_items = []
        for booking in paginated_queryset:
            is_owner = booking.made_by_id == request.user.id
            booking_items.append(
                {
                    "booking": booking,
                    "is_booking_owner": is_owner,
                    "selection_reason": "made_by" if is_owner else "attendee_linked",
                    "can_manage_all_attendees": is_owner,
                }
            )

        serializer = EventMyBookingResponseSerializer(
            {
                "event": event,
                "primary_booking_reference": (
                    paginated_queryset[0].booking_reference
                    if paginated_queryset
                    else None
                ),
                "bookings": booking_items,
            },
            context={"request": request, "event": event},
        )
        return paginator.get_paginated_response(serializer.data)

    # ------------------------------------------------------------------
    # my_outstanding_booking_payments
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get Outstanding Booking Payments",
        description=(
            "Retrieve all outstanding (unpaid) payment records for the current authenticated user "
            "in this event. Supports pagination and filtering."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name="payment_status", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booked_after", type=OpenApiTypes.DATETIME, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booked_before", type=OpenApiTypes.DATETIME, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="booked_in_days", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="attendee_name", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="page", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY),
        ],
        responses={
            200: OpenApiResponse(description="Paginated list of outstanding payments"),
            401: OpenApiResponse(description="Authentication required"),
            404: OpenApiResponse(description="Event not found"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="my-outstanding-booking-payments",
        permission_classes=[permissions.IsAuthenticated],
    )
    def my_outstanding_booking_payments(self, request, url_safe_title=None):
        event = self.get_object()

        outstanding_qs = (
            OutstandingPaymentsService.get_user_outstanding_payments_with_validation(
                request.user, event
            ).order_by("-created_at")
        )

        filterset = EventMyOutstandingPaymentsFilterSet(
            request.GET, queryset=outstanding_qs, request=request
        )
        filtered_queryset = filterset.qs

        paginator = StandardPagination()
        paginated_queryset = paginator.paginate_queryset(filtered_queryset, request)
        if paginated_queryset is None:
            paginated_queryset = filtered_queryset

        serializer = EventMyOutstandingPaymentSerializer(
            paginated_queryset,
            many=True,
            context={"request": request, "event": event},
        )
        return paginator.get_paginated_response(serializer.data)

    # ------------------------------------------------------------------
    # my_payment_summary
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get Unified Payment Summary For Current User Booking",
        description=(
            "Retrieve a booking payment summary for the current authenticated user. "
            "The response keeps separate sections for booking, shop, attendee, and outstanding "
            "payments, but each payment_id is canonical and appears in only one section."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="booking_reference",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional booking reference to target a specific booking.",
            ),
            OpenApiParameter(
                name="attendee_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional attendee UUID filter for attendee-specific payment section.",
            ),
        ],
        responses={
            200: EventMyPaymentSummarySerializer,
            401: OpenApiResponse(description="Authentication required"),
            404: OpenApiResponse(description="Event or booking not found"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="my-payment-summary",
        permission_classes=[permissions.IsAuthenticated],
    )
    def my_payment_summary(self, request, url_safe_title=None):
        event = self.get_object()

        bookings_qs = (
            Booking.objects.filter(event=event)
            .filter(Q(made_by=request.user) | Q(attendees__user=request.user))
            .distinct()
            .order_by("-booked_at", "-id")
        )

        booking_reference = request.query_params.get("booking_reference")
        if booking_reference:
            bookings_qs = bookings_qs.filter(booking_reference=booking_reference)

        booking = bookings_qs.first()
        if not booking:
            return Response(
                {"detail": "Booking not found for this event."},
                status=status.HTTP_404_NOT_FOUND,
            )

        attendee_filter = request.query_params.get("attendee_id")
        if attendee_filter:
            attendee_filter = self._resolve_attendee_filter(
                attendee_filter, booking, event
            )
            if isinstance(attendee_filter, Response):
                return attendee_filter  # propagate early error response

        payload = EventPaymentSummaryService.build_for_booking(
            booking=booking,
            event=event,
            attendee_filter=attendee_filter,
        )
        serializer = EventMyPaymentSummarySerializer(payload, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_attendee_filter(attendee_filter: str, booking, event):
        """
        Resolve an attendee_id param to a canonical UUID string.

        Accepts:
        - UUID string  → returned unchanged after validation
        - "firstname-lastname" → resolved to attendee UUID

        Returns the resolved UUID string, or a Response on error.
        """
        try:
            uuid.UUID(attendee_filter)
            return attendee_filter
        except ValueError:
            pass

        # Try first-last name parsing
        try:
            first_name, last_name = attendee_filter.split("-", 1)
        except ValueError:
            return Response(
                {
                    "detail": (
                        "Invalid attendee_id format. "
                        "Must be UUID or first-last name separated by hyphen."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db.models import Q as DjangoQ

        attendee = booking.attendees.filter(
            DjangoQ(
                user__first_name__iexact=first_name,
                user__last_name__iexact=last_name,
            )
            | DjangoQ(attendee_display_id=attendee_filter)
        ).first()

        if attendee:
            return str(attendee.attendee_id)

        return Response(
            {"detail": "Attendee not found for this booking."},
            status=status.HTTP_404_NOT_FOUND,
        )
