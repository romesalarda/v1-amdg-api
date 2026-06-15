"""
EventStaffActionsMixin — staff management actions for EventViewSet.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.models import EventStaff
from apps.events.api.serializers import EventStaffSerializer
from apps.events.api.permissions import (
    IsEventOwnerOrDjangoStaff,
    CannotTargetEventCreator,
)
from apps.events.services.notifications import (
    create_notification,
    NotificationTypeChoices,
)


class EventStaffActionsMixin:
    """Mixin providing staff management @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # add_staff
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Add Staff to Event",
        description=(
            "Add a user as a staff member to the event with optional notes. "
            "Creates an EventStaff instance linking the user to the event. "
            "Only event creators and superusers can add staff members. "
            "Returns validation error if user is already a staff member."
        ),
        tags=["Events"],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "User ID to add as staff"},
                    "notes": {"type": "string", "description": "Optional notes about the staff member"},
                },
                "required": ["user_id"],
            }
        },
        responses={
            201: EventStaffSerializer,
            400: OpenApiResponse(description="Bad request - validation errors"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="User not found"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="add-staff",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def add_staff(self, request, url_safe_title=None):
        event = self.get_object()

        user_id = request.data.get("user_id")
        notes = request.data.get("notes", "")

        if not user_id:
            return Response(
                {"detail": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if EventStaff.objects.filter(event=event, user=user).exists():
            return Response(
                {"detail": "User is already a staff member of this event"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        staff_member = EventStaff.objects.create(
            event=event,
            user=user,
            assigned_by=request.user,
            notes=notes,
        )

        create_notification(
            event=event,
            notification_type=NotificationTypeChoices.GENERAL,
            message=(
                f"{request.user.get_full_name()} added "
                f"{user.get_full_name()} as staff to the event."
            ),
        )

        serializer = EventStaffSerializer(staff_member)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # remove_staff
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Remove Staff from Event",
        description=(
            "Remove a staff member from an event by their staff ID. "
            "Permanently deletes the EventStaff instance. "
            "Only event creators and superusers can remove staff members. "
            "Requires staff_id query parameter."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="staff_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Staff member ID to remove",
                required=True,
            )
        ],
        responses={
            204: OpenApiResponse(description="Staff member removed successfully"),
            400: OpenApiResponse(description="Bad request - staff_id required"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Staff member not found"),
        },
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="remove-staff",
        permission_classes=[IsEventOwnerOrDjangoStaff, CannotTargetEventCreator],
    )
    def remove_staff(self, request, url_safe_title=None):
        event = self.get_object()

        staff_id = request.query_params.get("staff_id")
        if not staff_id:
            return Response(
                {"detail": "staff_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            staff_member = EventStaff.objects.get(staff_id=staff_id, event=event)
        except EventStaff.DoesNotExist:
            return Response(
                {"detail": "Staff member not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if staff_member.user_id == event.created_by_id:
            return Response(
                {"detail": CannotTargetEventCreator.message},
                status=status.HTTP_403_FORBIDDEN,
            )

        full_name = staff_member.user.get_full_name()
        staff_member.delete()

        create_notification(
            event=event,
            notification_type=NotificationTypeChoices.GENERAL,
            message=(
                f"{request.user.get_full_name()} removed "
                f"{full_name} from the event staff."
            ),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # staff_list
    # ------------------------------------------------------------------

    @extend_schema(
        summary="List Event Staff",
        description=(
            "Retrieve a complete list of all staff members assigned to the event. "
            "Includes user details, assignment information, and associated notes. "
            "Automatically includes related user and assigned_by data for efficient queries."
        ),
        tags=["Events"],
        responses={200: EventStaffSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="staff-list")
    def staff_list(self, request, url_safe_title=None):
        event = self.get_object()
        staff_members = event.staff_members.select_related("user", "assigned_by").all()
        serializer = EventStaffSerializer(staff_members, many=True)
        return Response(serializer.data)
