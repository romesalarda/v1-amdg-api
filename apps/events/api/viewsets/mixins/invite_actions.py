"""
EventInviteActionsMixin — staff invite actions for EventViewSet.
"""
from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.models import Event, EventStaffInvite
from apps.events.api.serializers import (
    EventStaffSerializer,
    EventStaffInviteSerializer,
    EventStaffInviteListSerializer,
)
from apps.events.api.permissions import IsEventOwnerOrEventStaffOrDjangoStaff
from rest_framework.permissions import IsAuthenticated
from apps.events.services.notifications import (
    create_notification,
    NotificationTypeChoices,
)


class EventInviteActionsMixin:
    """Mixin providing staff invite @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # staff_invites  (GET list / POST create)
    # ------------------------------------------------------------------

    @extend_schema(
        methods=["GET"],
        operation_id="event_staff_invites_list",
        summary="List Event Staff Invites",
        description=(
            "Retrieve a paginated list of all staff invites for this specific event. "
            "Event creators and existing staff members can view ALL invites. "
            "Regular authenticated users can only see invites where they are the target user.\n\n"
            "**Filtering Options:**\n"
            "- `accepted`: Filter by whether invite has been accepted (true/false)\n"
            "- `is_valid`: Filter by validity status\n"
            "- `target_user`: Filter by target user ID\n"
            "- `search`: Search by target user email address"
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(name="url_safe_title", type=OpenApiTypes.STR, location=OpenApiParameter.PATH, required=True),
            OpenApiParameter(name="accepted", type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="is_valid", type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="target_user", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="search", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(response=EventStaffInviteListSerializer(many=True)),
            401: OpenApiResponse(description="Authentication required"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Event not found"),
        },
    )
    @extend_schema(
        methods=["POST"],
        operation_id="event_staff_invites_create",
        summary="Create Event Staff Invite",
        description=(
            "Create a new staff invite to invite a user to join the event staff team. "
            "Only event creators and existing event staff members can create invites."
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(name="url_safe_title", type=OpenApiTypes.STR, location=OpenApiParameter.PATH, required=True),
        ],
        request=EventStaffInviteSerializer,
        responses={
            201: OpenApiResponse(response=EventStaffInviteSerializer),
            400: OpenApiResponse(description="Validation errors"),
            401: OpenApiResponse(description="Authentication required"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Event not found"),
        },
    )
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="staff-invites",
        permission_classes=[IsEventOwnerOrEventStaffOrDjangoStaff, IsAuthenticated],
    )
    def staff_invites(self, request, url_safe_title=None):
        event = get_object_or_404(Event, url_safe_title=url_safe_title)

        if request.method == "GET":
            queryset = (
                EventStaffInvite.objects.filter(event=event)
                .select_related("target_user", "invited_by")
                .order_by("-added_at")
            )

            # Non-managers can only see their own invites
            user = request.user
            is_manager = (
                user == event.created_by
                or event.staff_members.filter(user=user).exists()
                or user.is_staff
                or user.is_superuser
            )
            if not is_manager:
                queryset = queryset.filter(target_user=user)

            accepted = request.query_params.get("accepted")
            if accepted is not None:
                queryset = queryset.filter(accepted=accepted.lower() in ["true", "1", "yes"])

            is_valid_param = request.query_params.get("is_valid")
            if is_valid_param is not None and is_valid_param.lower() in ["true", "1", "yes"]:
                queryset = queryset.filter(is_active=True, accepted=False).filter(
                    Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
                )

            target_user = request.query_params.get("target_user")
            if target_user:
                queryset = queryset.filter(target_user_id=target_user)

            search = request.query_params.get("search")
            if search:
                queryset = queryset.filter(
                    Q(target_user__email__icontains=search)
                    | Q(target_user__first_name__icontains=search)
                    | Q(target_user__last_name__icontains=search)
                    | Q(target_user__username__icontains=search)
                )

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = EventStaffInviteListSerializer(
                    page,
                    many=True,
                    context={"request": request, "event": event.url_safe_title},
                )
                return self.get_paginated_response(serializer.data)

            serializer = EventStaffInviteListSerializer(
                queryset,
                many=True,
                context={"request": request, "event": event.url_safe_title},
            )
            return Response(serializer.data)

        # POST — IsEventOwnerOrEventStaffOrDjangoStaff is enforced via has_object_permission
        # when get_object() is called above; check explicitly for create path
        user = request.user
        is_manager = (
            user == event.created_by
            or event.staff_members.filter(user=user).exists()
            or user.is_staff
            or user.is_superuser
        )
        if not is_manager:
            return Response(
                {"detail": "You do not have permission to create invites for this event."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = EventStaffInviteSerializer(
            data=request.data,
            context={"request": request, "event": event.url_safe_title},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # manage_staff_invite  (GET / PUT / PATCH / DELETE)
    # ------------------------------------------------------------------

    @extend_schema(methods=["GET"], operation_id="event_staff_invite_retrieve", summary="Retrieve Staff Invite Details", tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(name="url_safe_title", type=OpenApiTypes.STR, location=OpenApiParameter.PATH, required=True),
            OpenApiParameter(name="invite_id", type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, required=True),
        ],
        responses={200: OpenApiResponse(response=EventStaffInviteSerializer), 401: OpenApiResponse(description="Authentication required"), 403: OpenApiResponse(description="Permission denied"), 404: OpenApiResponse(description="Not found")},
    )
    @extend_schema(methods=["PUT"], operation_id="event_staff_invite_update", summary="Full Update Staff Invite", tags=["Events", "Event Staff Invites"],
        request=EventStaffInviteSerializer,
        responses={200: OpenApiResponse(response=EventStaffInviteSerializer), 400: OpenApiResponse(description="Validation errors"), 403: OpenApiResponse(description="Permission denied"), 404: OpenApiResponse(description="Not found")},
    )
    @extend_schema(methods=["PATCH"], operation_id="event_staff_invite_partial_update", summary="Partial Update Staff Invite", tags=["Events", "Event Staff Invites"],
        request=EventStaffInviteSerializer,
        responses={200: OpenApiResponse(response=EventStaffInviteSerializer), 400: OpenApiResponse(description="Validation errors"), 403: OpenApiResponse(description="Permission denied"), 404: OpenApiResponse(description="Not found")},
    )
    @extend_schema(methods=["DELETE"], operation_id="event_staff_invite_delete", summary="Delete Staff Invite", tags=["Events", "Event Staff Invites"],
        responses={204: OpenApiResponse(description="Deleted"), 403: OpenApiResponse(description="Permission denied"), 404: OpenApiResponse(description="Not found")},
    )
    @action(
        detail=True,
        methods=["get", "put", "patch", "delete"],
        url_path=r"staff-invites/(?P<invite_id>[^/.]+)",
        permission_classes=[IsAuthenticated],
    )
    def manage_staff_invite(self, request, url_safe_title=None, invite_id=None):
        event = self.get_object()

        try:
            invite = EventStaffInvite.objects.select_related(
                "target_user", "invited_by"
            ).get(id=invite_id, event=event)
        except EventStaffInvite.DoesNotExist:
            return Response(
                {"detail": "Staff invite not found for this event."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except EventStaffInvite.MultipleObjectsReturned:
            return Response(
                {"detail": "Multiple invites found with the same ID for this event."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except ValueError:
            return Response(
                {"detail": "Invalid invite ID format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        is_manager = (
            user == event.created_by
            or event.staff_members.filter(user=user).exists()
            or user.is_staff
            or user.is_superuser
        )

        if request.method == "GET":
            # Target user can also view their own invite
            if not is_manager and invite.target_user != user:
                return Response(
                    {"detail": "You do not have permission to view this invite."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer = EventStaffInviteSerializer(
                invite, context={"request": request, "event": event.url_safe_title}
            )
            return Response(serializer.data)

        # PUT / PATCH / DELETE require manager role
        if not is_manager:
            return Response(
                {"detail": "You do not have permission to manage this invite."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method in ["PUT", "PATCH"]:
            partial = request.method == "PATCH"
            serializer = EventStaffInviteSerializer(
                invite,
                data=request.data,
                partial=partial,
                context={"request": request, "event": event.url_safe_title},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        # DELETE — soft deactivate
        invite.is_active = False
        invite.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # accept_invite
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Accept Event Staff Invite",
        description=(
            "Accept a staff invitation. Only the invite target can accept it. "
            "On success, an EventStaff record is created and the invite is marked accepted."
        ),
        tags=["Events", "Event Staff Invites"],
        parameters=[
            OpenApiParameter(name="url_safe_title", type=OpenApiTypes.STR, location=OpenApiParameter.PATH, required=True),
            OpenApiParameter(name="invite_id", type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, required=True),
        ],
        request=None,
        responses={
            200: OpenApiResponse(description="Invite accepted; EventStaff created."),
            400: OpenApiResponse(description="Invite not valid for acceptance."),
            401: OpenApiResponse(description="Authentication required."),
            403: OpenApiResponse(description="Not the invite target."),
            404: OpenApiResponse(description="Invite not found."),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"staff-invites/(?P<invite_id>[^/.]+)/accept",
        permission_classes=[IsAuthenticated],
    )
    def accept_invite(self, request, url_safe_title=None, invite_id=None):
        event = self.get_non_restrictive_object()

        try:
            invite = EventStaffInvite.objects.get(id=invite_id, event=event)
        except EventStaffInvite.DoesNotExist:
            return Response(
                {"detail": "Staff invite not found for this event."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError:
            return Response(
                {"detail": "Invalid invite ID format."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if invite.target_user != request.user:
            return Response(
                {"detail": "You can only accept invites sent to you."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not invite.is_valid:
            if not invite.is_active:
                error_msg = "This invite has been deactivated."
            elif invite.accepted:
                error_msg = "This invite has already been accepted."
            elif invite.expires_at and invite.expires_at < timezone.now():
                error_msg = "This invite has expired."
            else:
                error_msg = "This invite is no longer valid."
            return Response({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)

        try:
            staff = invite.accept_invite()
            serializer = EventStaffSerializer(staff, context={"request": request})

            create_notification(
                event=event,
                message=(
                    f"{request.user.get_full_name()} has accepted the staff invite "
                    "and joined the event team."
                ),
                notification_type=NotificationTypeChoices.GENERAL,
                metadata={"user_id": request.user.id, "event_id": event.id},
            )

            return Response(
                {
                    "message": "Invite accepted successfully. You are now an event staff member.",
                    "staff": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except ValueError as exc:
            return Response(
                {"error": f"Failed to accept invite: {str(exc)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
