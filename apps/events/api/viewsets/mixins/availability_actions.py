"""
EventAvailabilityActionsMixin — availability window and template actions for EventViewSet.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.models import Event
from apps.common.models import AvailabilityWindow, AvailabilityWindowTemplate
from apps.common.api.serializers import (
    AvailabilityWindowSerializer,
    AvailabilityWindowTemplateSerializer,
)
from apps.events.api.permissions import IsEventOwnerOrDjangoStaff
from apps.events.services.notifications import (
    create_notification,
    NotificationTypeChoices,
)
from apps.organisations.models import Organisation

logger = logging.getLogger(__name__)


class EventAvailabilityActionsMixin:
    """Mixin providing availability window and template @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # availability_windows  (read)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="List Availability Windows",
        description=(
            "Retrieve all availability windows configured for the event. "
            "Availability windows define time slots when the event is open for registrations or bookings."
        ),
        tags=["Events"],
        responses={200: AvailabilityWindowSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="availability-windows")
    def availability_windows(self, request, url_safe_title=None):
        event = self.get_object()
        windows = event.extended_availability_windows.all()

        paginated = self.paginate_queryset(windows)
        if paginated is not None:
            serializer = AvailabilityWindowSerializer(
                paginated, many=True, context={"request": request}
            )
            return self.get_paginated_response(serializer.data)
        serializer = AvailabilityWindowSerializer(windows, many=True, context={"request": request})
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # add_availability_window  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Add Availability Window",
        description=(
            "Add a new availability window to the event defining when registrations are open. "
            "Only event creators and superusers can add availability windows."
        ),
        tags=["Events"],
        request=AvailabilityWindowSerializer,
        responses={
            201: AvailabilityWindowSerializer,
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="add-availability-window",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def add_availability_window(self, request, url_safe_title=None):
        event = self.get_object()
        serializer = AvailabilityWindowSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Event)
            window = serializer.save(target_type=content_type, target_id=event.id)
            return Response(
                AvailabilityWindowSerializer(window, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # remove_availability_window  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Remove Availability Window",
        description=(
            "Remove an availability window from the event by its window ID. "
            "Only event creators and superusers can remove availability windows."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="window_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Availability window ID to remove",
                required=True,
            )
        ],
        responses={
            204: OpenApiResponse(description="Window removed successfully"),
            400: OpenApiResponse(description="Bad request"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Window not found"),
        },
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="remove-availability-window",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def remove_availability_window(self, request, url_safe_title=None):
        event = self.get_object()

        window_id = request.query_params.get("window_id")
        if not window_id:
            return Response(
                {"detail": "window_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            window = AvailabilityWindow.objects.get(
                availability_id=window_id, target_id=event.id
            )
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        window_name = window.name
        window.delete()
        create_notification(
            event=event,
            notification_type=NotificationTypeChoices.GENERAL,
            message=(
                f"{request.user.get_full_name()} removed "
                f"{window_name} from the event availability windows."
            ),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # update_availability_window  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Update Availability Window",
        description=(
            "Update an existing availability window for the event. "
            "Allows partial updates (PATCH) or full updates (PUT). "
            "Only event creators and superusers can update availability windows. "
            "The window_id can be provided as a query parameter or in the request body as 'availability_id'."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="window_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="Availability window ID to update. Can also be provided in request body as availability_id.",
                required=False,
            )
        ],
        request=AvailabilityWindowSerializer,
        responses={
            200: AvailabilityWindowSerializer,
            400: OpenApiResponse(description="Invalid data or missing window_id"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Window not found for this event"),
        },
    )
    @action(
        detail=True,
        methods=["patch", "put"],
        url_path="update-availability-window",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def update_availability_window(self, request, url_safe_title=None):
        event = self.get_object()

        window_id = request.query_params.get("window_id") or request.data.get("availability_id")
        if not window_id:
            return Response(
                {"detail": "window_id query parameter or availability_id in request body is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            content_type = ContentType.objects.get_for_model(Event)
            window = AvailabilityWindow.objects.get(
                availability_id=window_id,
                target_id=event.id,
                target_type=content_type,
            )
        except AvailabilityWindow.DoesNotExist:
            return Response(
                {"detail": "Availability window not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        partial = request.method == "PATCH"
        old_window = AvailabilityWindowSerializer(window).data

        serializer = AvailabilityWindowSerializer(
            window,
            data=request.data,
            partial=partial,
            context={"request": request},
        )

        if serializer.is_valid():
            logger.info(
                "Updating availability window %s for event %s by user %s",
                window.availability_id,
                event.id,
                request.user.id,
            )
            new_window = serializer.save()

            changes = []
            if old_window["name"] != new_window.name:
                changes.append(f"name changed to '{new_window.name}'")
            if old_window["available_from"] != new_window.available_from:
                changes.append(f"'available from' changed to '{new_window.available_from}'")
            if old_window["available_to"] != new_window.available_to:
                changes.append(f"'available to' changed to '{new_window.available_to}'")
            if old_window["availability_type"] != new_window.availability_type:
                changes.append(f"availability type changed to '{new_window.availability_type}'")
            if old_window["description"] != new_window.description:
                changes.append("description updated")

            if changes:
                create_notification(
                    event=event,
                    notification_type=NotificationTypeChoices.GENERAL,
                    message=(
                        f"{request.user.get_full_name()} updated the availability window "
                        f"'{old_window['name']}': " + ", ".join(changes)
                    ),
                )
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # availability_templates  (read, detail=False)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="List Availability Window Templates",
        description=(
            "Retrieve all available templates for creating availability windows. "
            "Includes both system-defined predefined templates and custom templates "
            "created by the user's organization."
        ),
        tags=["Events", "Availability Windows"],
        responses={200: AvailabilityWindowTemplateSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="availability-templates")
    def availability_templates(self, request):
        if not request.user.is_authenticated:
            return Response(
                {"detail": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_orgs = Organisation.objects.filter(memberships__user=request.user)

        templates = (
            AvailabilityWindowTemplate.objects.filter(
                Q(created_by=request.user)
                | Q(is_predefined=True, organisation__in=user_orgs)
            )
            .distinct()
            .order_by("-created_at")
        )

        paginated = self.paginate_queryset(templates)
        if paginated is not None:
            serializer = AvailabilityWindowTemplateSerializer(
                paginated, many=True, context={"request": request}
            )
            return self.get_paginated_response(serializer.data)

        serializer = AvailabilityWindowTemplateSerializer(
            templates, many=True, context={"request": request}
        )
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # manage_availability_template  (PATCH / DELETE, detail=False)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Manage Availability Window Template",
        description=(
            "Update (PATCH) or delete (DELETE) an availability window template. "
            "Only the creator of the template can modify it. Predefined templates cannot be modified. "
            "For updates: only name and description can be changed."
        ),
        tags=["Events", "Availability Windows"],
        parameters=[
            OpenApiParameter(
                name="template_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                description="UUID of the template to update or delete",
                required=True,
            )
        ],
        request=AvailabilityWindowTemplateSerializer,
        responses={
            200: AvailabilityWindowTemplateSerializer,
            204: {"description": "Template deleted successfully"},
            400: {"description": "Missing or invalid template_id"},
            403: {"description": "Permission denied - not the creator or template is predefined"},
            404: {"description": "Template not found"},
        },
    )
    @action(
        detail=False,
        methods=["patch", "delete"],
        url_path="availability-templates/manage",
        url_name="manage-availability-template",
    )
    def manage_availability_template(self, request, **kwargs):
        template_id = request.query_params.get("template_id")
        if not template_id:
            return Response(
                {"detail": "template_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            template = AvailabilityWindowTemplate.objects.get(template_id=template_id)
        except AvailabilityWindowTemplate.DoesNotExist:
            return Response(
                {"detail": "Template not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if template.is_predefined:
            verb = "modified" if request.method == "PATCH" else "deleted"
            return Response(
                {"detail": f"Predefined templates cannot be {verb}"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if template.created_by != request.user:
            verb = "edit" if request.method == "PATCH" else "delete"
            return Response(
                {"detail": f"Only the creator can {verb} this template"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == "DELETE":
            template.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        allowed_fields = {"name", "description"}
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}

        serializer = AvailabilityWindowTemplateSerializer(
            template,
            data=update_data,
            partial=True,
            context={"request": request},
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # preview_template_application  (read)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Preview Template Application",
        description=(
            "Preview what availability windows would be created if this template is applied to the event. "
            "Returns a list of windows that would be created with their calculated dates, "
            "plus any conflicts with existing windows."
        ),
        tags=["Events", "Availability Windows"],
        parameters=[
            OpenApiParameter(
                name="template_id",
                type=str,
                location=OpenApiParameter.QUERY,
                description="ID of the template to preview",
                required=True,
            ),
        ],
        responses={
            200: {
                "description": "Preview data with windows and conflicts",
                "type": "object",
                "properties": {
                    "windows": {"type": "array"},
                    "conflicts": {"type": "array"},
                    "has_conflicts": {"type": "boolean"},
                },
            },
            404: {"description": "Event or template not found"},
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="preview-template-application",
        url_name="preview-template-application",
    )
    def preview_template_application(self, request, url_safe_title=None, **kwargs):
        template_id = request.query_params.get("template_id")
        if not template_id:
            return Response(
                {"detail": "template_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = self.get_object()

        try:
            template = AvailabilityWindowTemplate.objects.get(template_id=template_id)
        except AvailabilityWindowTemplate.DoesNotExist:
            return Response({"detail": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        if not event.start_datetime:
            return Response(
                {"detail": "Event must have a start date to apply template"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_windows = AvailabilityWindow.objects.filter(
            availability_type=ContentType.objects.get_for_model(Event),
            target_id=event.event_id,
        )

        preview_windows = []
        conflicts = []

        for window_config in template.windows_config:
            available_from = event.start_datetime + timedelta(
                days=window_config["offset_from_event_start"]
            )
            available_to = event.start_datetime + timedelta(
                days=window_config["offset_to_event_start"]
            )

            window_data = {
                "name": window_config.get(
                    "name",
                    window_config["availability_type"].replace("_", " ").title(),
                ),
                "description": window_config.get("description"),
                "availability_type": window_config["availability_type"],
                "available_from": available_from.isoformat(),
                "available_to": available_to.isoformat(),
            }
            preview_windows.append(window_data)

            for existing in existing_windows:
                if not existing.available_from or not existing.available_to:
                    continue
                if available_from < existing.available_to and available_to > existing.available_from:
                    is_same_type = (
                        existing.availability_type == window_config["availability_type"]
                    )
                    conflicts.append(
                        {
                            "new_window": window_data["name"],
                            "existing_window": existing.name,
                            "conflict_type": (
                                "same_type_overlap" if is_same_type else "different_type_overlap"
                            ),
                            "severity": "high" if is_same_type else "medium",
                            "message": (
                                f"{'Same type ' if is_same_type else ''}Overlap with existing window '{existing.name}'"
                            ),
                            "existing_window_details": {
                                "name": existing.name,
                                "type": existing.availability_type,
                                "from": existing.available_from.isoformat(),
                                "to": existing.available_to.isoformat(),
                            },
                        }
                    )

        return Response(
            {
                "windows": preview_windows,
                "conflicts": conflicts,
                "has_conflicts": bool(conflicts),
                "conflict_summary": (
                    f"{len(conflicts)} conflict(s) detected" if conflicts else "No conflicts"
                ),
            }
        )

    # ------------------------------------------------------------------
    # apply_availability_template  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Apply Template to Event",
        description=(
            "Apply an availability window template to the event. Creates multiple "
            "availability windows based on the template configuration. "
            "Each window's dates are calculated using offsets from the event start date."
        ),
        tags=["Events", "Availability Windows"],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the template to apply",
                    }
                },
                "required": ["template_id"],
            }
        },
        responses={
            201: AvailabilityWindowSerializer(many=True),
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="apply-availability-template",
        permission_classes=[IsEventOwnerOrDjangoStaff],
        url_name="apply-availability-template",
    )
    def apply_availability_template(self, request, url_safe_title=None, **kwargs):
        event = self.get_object()

        template_id = request.data.get("template_id")
        if not template_id:
            return Response({"detail": "template_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            template = AvailabilityWindowTemplate.objects.get(template_id=template_id)
        except AvailabilityWindowTemplate.DoesNotExist:
            return Response({"detail": "Template not found"}, status=status.HTTP_404_NOT_FOUND)

        user_orgs = Organisation.objects.filter(memberships__user=request.user)
        is_accessible = template.created_by == request.user or (
            template.is_predefined and template.organisation in user_orgs
        )
        if not is_accessible:
            return Response(
                {"detail": "You don't have access to this template"},
                status=status.HTTP_403_FORBIDDEN,
            )

        existing_windows = AvailabilityWindow.objects.filter(
            availability_type=ContentType.objects.get_for_model(Event),
            target_id=event.event_id,
        )

        conflicts = []
        for window_config in template.windows_config:
            available_from = event.start_datetime + timedelta(
                days=window_config["offset_from_event_start"]
            )
            available_to = event.start_datetime + timedelta(
                days=window_config["offset_to_event_start"]
            )
            for existing in existing_windows:
                if not existing.available_from or not existing.available_to:
                    continue
                if available_from < existing.available_to and available_to > existing.available_from:
                    conflicts.append(
                        {
                            "new_window": window_config.get("name", window_config["availability_type"]),
                            "existing_window": existing.name,
                            "same_type": existing.availability_type == window_config["availability_type"],
                        }
                    )

        try:
            created_windows = template.apply_to_event(event, timezone=event.timezone)
            serializer = AvailabilityWindowSerializer(
                created_windows, many=True, context={"request": request}
            )
            return Response(
                {
                    "windows": serializer.data,
                    "conflicts_detected": conflicts,
                    "message": (
                        f"Created {len(created_windows)} availability window(s)"
                        + (f" with {len(conflicts)} overlap(s)" if conflicts else "")
                    ),
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as exc:
            return Response(
                {"detail": f"Failed to apply template: {str(exc)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # ------------------------------------------------------------------
    # save_windows_as_template  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Save Current Windows as Template",
        description=(
            "Save the current event's availability windows as a reusable template. "
            "The template will be associated with your organization and can be applied to future events."
        ),
        tags=["Events", "Availability Windows"],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the template"},
                    "description": {"type": "string", "description": "Optional description"},
                },
                "required": ["name"],
            }
        },
        responses={
            201: AvailabilityWindowTemplateSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="save-windows-as-template",
        permission_classes=[IsEventOwnerOrDjangoStaff],
        url_name="save-windows-as-template",
    )
    def save_windows_as_template(self, request, url_safe_title=None, **kwargs):
        event = self.get_object()

        name = request.data.get("name")
        if not name:
            return Response(
                {"detail": "Template name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        windows = event.availability_windows.all()
        if not windows:
            return Response(
                {"detail": "Event has no availability windows to save"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_start = event.start_datetime
        windows_config = []
        for window in windows:
            offset_from = (window.available_from - event_start).total_seconds() / (24 * 3600)
            offset_to = (window.available_to - event_start).total_seconds() / (24 * 3600)
            windows_config.append(
                {
                    "name": window.name,
                    "description": window.description or "",
                    "availability_type": window.availability_type,
                    "offset_from_event_start": round(offset_from, 2),
                    "offset_to_event_start": round(offset_to, 2),
                }
            )

        template = AvailabilityWindowTemplate.objects.create(
            name=name,
            description=request.data.get("description", ""),
            is_predefined=False,
            organisation=event.organisation,
            windows_config=windows_config,
            created_by=request.user,
        )

        serializer = AvailabilityWindowTemplateSerializer(template, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
