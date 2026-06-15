"""
EventPermissionActionsMixin — permission assignment/revoke/check actions for EventViewSet.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.models import (
    EventPermission,
    EventPermissionAssignment,
    EventRoleAssignment,
)
from apps.events.api.serializers import EventPermissionAssignmentSerializer
from apps.events.api.permissions import IsEventOwnerOrDjangoStaff
from apps.events.services.notifications import (
    create_notification,
    NotificationTypeChoices,
)


class EventPermissionActionsMixin:
    """Mixin providing permission management @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # assign_permission  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Assign Permission to User",
        description=(
            "Assign a specific permission to a user for this event with CRUD flags. "
            "Only event creators and superusers can assign permissions."
        ),
        tags=["Events"],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "permission_id": {"type": "integer"},
                    "read_only": {"type": "boolean", "default": False},
                    "allow_create": {"type": "boolean", "default": False},
                    "allow_update": {"type": "boolean", "default": False},
                    "allow_delete": {"type": "boolean", "default": False},
                },
                "required": ["user_id", "permission_id"],
            }
        },
        responses={
            201: EventPermissionAssignmentSerializer,
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="assign-permission",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def assign_permission(self, request, pk=None):
        event = self.get_object()

        user_id = request.data.get("user_id")
        permission_id = request.data.get("permission_id")

        if not user_id or not permission_id:
            return Response(
                {"detail": "user_id and permission_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            permission = EventPermission.objects.get(id=permission_id)
        except EventPermission.DoesNotExist:
            return Response({"detail": "Permission not found"}, status=status.HTTP_404_NOT_FOUND)

        read_only = request.data.get("read_only", False)
        allow_create = request.data.get("allow_create", False)
        allow_update = request.data.get("allow_update", False)
        allow_delete = request.data.get("allow_delete", False)

        assignment, created = EventPermissionAssignment.objects.get_or_create(
            event=event,
            user=user,
            permission=permission,
            defaults={
                "assigned_by": request.user,
                "read_only": read_only,
                "allow_create": allow_create,
                "allow_update": allow_update,
                "allow_delete": allow_delete,
            },
        )

        if not created:
            assignment.read_only = read_only
            assignment.allow_create = allow_create
            assignment.allow_update = allow_update
            assignment.allow_delete = allow_delete
            assignment.save()

            serializer = EventPermissionAssignmentSerializer(
                assignment, context={"request": request}
            )
            return Response(serializer.data, status=status.HTTP_200_OK)

        create_notification(
            event=event,
            message=(
                f"{user.get_full_name()} has been granted {permission.name} "
                f"permission for {event.title}."
            ),
            notification_type=NotificationTypeChoices.GENERAL,
            metadata={"user_id": user.id, "permission_id": permission.id, "event_id": event.id},
        )

        serializer = EventPermissionAssignmentSerializer(assignment, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # revoke_permission  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Revoke Permission from User",
        description=(
            "Revoke a specific permission from a user for this event. "
            "Only event creators and superusers can revoke permissions."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="assignment_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Permission assignment ID to revoke",
                required=True,
            )
        ],
        responses={
            204: OpenApiResponse(description="Permission revoked successfully"),
            400: OpenApiResponse(description="Bad request"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Assignment not found"),
        },
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="revoke-permission",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def revoke_permission(self, request, *args, **kwargs):
        event = self.get_object()

        assignment_id = request.query_params.get("assignment_id")
        if not assignment_id:
            return Response(
                {"detail": "assignment_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            assignment = EventPermissionAssignment.objects.get(
                id=assignment_id, event=event
            )
        except EventPermissionAssignment.DoesNotExist:
            return Response(
                {"detail": "Permission assignment not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        user_name = assignment.user.get_full_name()
        permission_name = assignment.permission.name
        assignment.delete()

        create_notification(
            event=event,
            message=(
                f"{user_name}'s {permission_name} permission has been revoked for {event.title}."
            ),
            notification_type=NotificationTypeChoices.GENERAL,
            metadata={
                "user_id": assignment.user.id,
                "permission_id": assignment.permission.id,
                "event_id": event.id,
            },
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # check_user_permissions  (read)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Check User Permissions for Event",
        description=(
            "Get comprehensive permission information for a user on this event. "
            "If `user_id` query param is provided, checks permissions for that user "
            "(requires admin/owner access). Otherwise checks the current authenticated user."
        ),
        tags=["Events", "Permissions"],
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Optional: Check permissions for a specific user ID.",
                required=False,
            )
        ],
        responses={
            200: OpenApiResponse(description="Comprehensive permission information for the user"),
            401: OpenApiResponse(description="Authentication required"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="User not found"),
        },
    )
    @action(detail=True, methods=["get"], url_path="check-permissions")
    def check_user_permissions(self, request, url_safe_title=None):
        event = self.get_object()

        user_id = request.query_params.get("user_id")
        if user_id:
            # Checking another user's permissions requires owner / admin access
            if not (
                request.user.is_staff
                or request.user.is_superuser
                or event.created_by == request.user
            ):
                return Response(
                    {"detail": "You don't have permission to check other users' permissions"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            User = get_user_model()
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        else:
            if not request.user.is_authenticated:
                return Response(
                    {"detail": "Authentication required"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            user = request.user

        is_creator = user == event.created_by
        is_admin = user.is_staff or user.is_superuser
        is_staff_member = (
            event.staff_members.filter(user=user).exists() if not is_creator else True
        )
        can_manage = is_creator or is_staff_member or is_admin

        permission_assignments = EventPermissionAssignment.objects.filter(
            event=event, user=user
        ).select_related("permission", "assigned_by")

        assigned_permissions = []
        for assignment in permission_assignments:
            if assignment.read_only:
                effective_access = {
                    "can_read": True,
                    "can_create": False,
                    "can_update": False,
                    "can_delete": False,
                }
            else:
                has_write = (
                    assignment.allow_update
                    or assignment.allow_delete
                    or assignment.allow_create
                )
                effective_access = {
                    "can_read": has_write,
                    "can_create": assignment.allow_create,
                    "can_update": assignment.allow_update,
                    "can_delete": assignment.allow_delete,
                }

            assigned_permissions.append(
                {
                    "id": assignment.id,
                    "permission_name": assignment.permission.name,
                    "permission_code": assignment.permission.code,
                    "permission_category": assignment.permission.category,
                    "permission_description": assignment.permission.description,
                    "read_only": assignment.read_only,
                    "allow_create": assignment.allow_create,
                    "allow_update": assignment.allow_update,
                    "allow_delete": assignment.allow_delete,
                    "has_full_access": assignment.has_full_access,
                    "effective_access": effective_access,
                    "assigned_at": assignment.assigned_at,
                    "assigned_by_email": (
                        assignment.assigned_by.email if assignment.assigned_by else None
                    ),
                    "assigned_by_name": (
                        assignment.assigned_by.get_full_name()
                        if assignment.assigned_by
                        else None
                    ),
                }
            )

        role_assignments = EventRoleAssignment.objects.filter(
            event=event, user=user
        ).select_related("role", "assigned_by")

        assigned_roles = [
            {
                "id": assignment.id,
                "role_name": assignment.role.name,
                "role_code": assignment.role.code,
                "role_category": assignment.role.category,
                "role_description": assignment.role.description,
                "assigned_at": assignment.assigned_at,
                "assigned_by_email": (
                    assignment.assigned_by.email if assignment.assigned_by else None
                ),
                "assigned_by_name": (
                    assignment.assigned_by.get_full_name()
                    if assignment.assigned_by
                    else None
                ),
            }
            for assignment in role_assignments
        ]

        return Response(
            {
                "user_id": user.id,
                "user_email": user.email,
                "user_name": user.get_full_name(),
                "is_creator": is_creator,
                "is_staff_member": is_staff_member,
                "is_admin": is_admin,
                "can_manage_event": can_manage,
                "can_manage_staff": can_manage,
                "can_manage_invites": can_manage,
                "can_manage_resources": can_manage,
                "can_delete_event": can_manage,
                "assigned_permissions": assigned_permissions,
                "assigned_roles": assigned_roles,
            }
        )
