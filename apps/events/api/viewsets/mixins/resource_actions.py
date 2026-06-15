"""
EventResourceActionsMixin — resource / landing-image actions for EventViewSet.
"""
from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.events.models import Event
from apps.common.models import Resource
from apps.common.api.serializers import ResourceSerializer
from apps.events.api.permissions import IsEventOwnerOrDjangoStaff
from apps.events.services.notifications import (
    create_notification,
    NotificationTypeChoices,
)


class EventResourceActionsMixin:
    """Mixin providing resource and landing-image @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # resources  (read)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="List Event Resources",
        description=(
            "Retrieve all resources associated with the event including documents, "
            "images, videos, and links. Supports filtering by tag and resource type."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(name="tag", type=OpenApiTypes.STR, description="Filter by resource tag"),
            OpenApiParameter(name="resource_type", type=OpenApiTypes.STR, description="Filter by resource type"),
        ],
        responses={200: ResourceSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="resources")
    def resources(self, request, url_safe_title=None):
        event = self.get_object()
        qs = event.resources.all()

        tag = request.query_params.get("tag")
        if tag:
            qs = qs.filter(tag__iexact=tag)

        resource_type = request.query_params.get("resource_type")
        if resource_type:
            qs = qs.filter(resource_type=resource_type)

        qs = qs.exclude(tag__in=["LANDING_PHOTO_MAIN", "LANDING_PHOTO_SECONDARY", "QUESTION_UPLOAD"])

        paginated = self.paginate_queryset(qs)
        if paginated is not None:
            serializer = ResourceSerializer(paginated, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = ResourceSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # add_resource  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Add Resource to Event",
        description=(
            "Add a new resource to the event such as documents, images, videos, "
            "audio files, or links. Only event creators and superusers can add resources."
        ),
        tags=["Events"],
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "tag": {"type": "string"},
                    "resource_type": {"type": "string", "enum": ["DOCUMENT", "IMAGE", "VIDEO", "AUDIO", "LINK", "OTHER"]},
                    "public": {"type": "boolean"},
                    "file": {"type": "string", "format": "binary"},
                    "image": {"type": "string", "format": "binary"},
                    "link": {"type": "string", "format": "uri"},
                },
                "required": ["name", "resource_type"],
            }
        },
        responses={
            201: ResourceSerializer,
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="add-resource",
        permission_classes=[IsEventOwnerOrDjangoStaff],
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def add_resource(self, request, url_safe_title=None):
        event = self.get_object()
        serializer = ResourceSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Event)
            resource = serializer.save(
                target_type=content_type,
                target_id=event.id,
                added_by=request.user,
            )
            return Response(
                ResourceSerializer(resource, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # add_landing_image  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Add Landing Image to Event",
        description=(
            "Add a landing image to the event. If set as main, any existing main "
            "landing image is automatically demoted to secondary. "
            "Only event creators and superusers can add landing images."
        ),
        tags=["Events"],
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "image": {"type": "string", "format": "binary"},
                    "is_main": {"type": "boolean"},
                    "public": {"type": "boolean"},
                },
                "required": ["name", "image"],
            }
        },
        responses={
            201: ResourceSerializer,
            400: OpenApiResponse(description="Validation errors"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="add-landing-image",
        permission_classes=[IsEventOwnerOrDjangoStaff],
        parser_classes=[MultiPartParser, FormParser],
    )
    def add_landing_image(self, request, url_safe_title=None):
        event = self.get_object()

        if "image" not in request.FILES:
            return Response(
                {"detail": "image file is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = {
            "name": request.data.get("name"),
            "description": request.data.get("description", ""),
            "resource_type": "IMAGE",
            "public": request.data.get("public", "true").lower() == "true",
            "image": request.FILES["image"],
        }

        serializer = ResourceSerializer(data=data, context={"request": request})
        if serializer.is_valid():
            content_type = ContentType.objects.get_for_model(Event)
            is_main = request.data.get("is_main", "true").lower() == "true"

            if is_main:
                event.resources.filter(tag="LANDING_PHOTO_MAIN").update(
                    tag="LANDING_PHOTO_SECONDARY"
                )

            resource = serializer.save(
                target_type=content_type,
                target_id=event.id,
                added_by=request.user,
                tag="LANDING_PHOTO_MAIN" if is_main else "LANDING_PHOTO_SECONDARY",
            )
            return Response(
                ResourceSerializer(resource, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # update_resource  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Update Resource Metadata",
        description=(
            "Update resource metadata such as name, description, tag, and public "
            "visibility. Only event creators and superusers can update resources."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="resource_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Resource ID to update",
                required=True,
            )
        ],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "tag": {"type": "string"},
                    "public": {"type": "boolean"},
                },
            }
        },
        responses={
            200: ResourceSerializer,
            400: OpenApiResponse(description="Bad request or protected resource"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Resource not found"),
        },
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path="update-resource",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def update_resource(self, request, url_safe_title=None):
        event = self.get_object()

        resource_id = request.query_params.get("resource_id")
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if resource.protected:
            return Response(
                {"detail": "This resource is protected and cannot be updated"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ResourceSerializer(
            resource,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        if serializer.is_valid():
            allowed_fields = {"name", "description", "tag", "public"}
            update_data = {
                k: v for k, v in serializer.validated_data.items() if k in allowed_fields
            }
            if not update_data:
                return Response(
                    {"detail": "No valid fields to update. Allowed fields: name, description, tag, public"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.save(**update_data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # promote_landing_image  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Promote Landing Image to Main",
        description=(
            "Promote a secondary landing image to main landing image. "
            "Automatically demotes the current main image to secondary. "
            "Only event creators and superusers can promote images."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="resource_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Resource ID of the secondary image to promote",
                required=True,
            )
        ],
        responses={
            200: ResourceSerializer,
            400: OpenApiResponse(description="Bad request - resource must be a landing image"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Resource not found"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="promote-landing-image",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def promote_landing_image(self, request, url_safe_title=None):
        event = self.get_object()

        resource_id = request.query_params.get("resource_id")
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if resource.tag not in ["LANDING_PHOTO_MAIN", "LANDING_PHOTO_SECONDARY"]:
            return Response(
                {"detail": "Resource must be a landing image (LANDING_PHOTO_MAIN or LANDING_PHOTO_SECONDARY)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if resource.tag == "LANDING_PHOTO_MAIN":
            return Response(
                {"detail": "Resource is already the main landing image"},
                status=status.HTTP_200_OK,
            )

        event.resources.filter(tag="LANDING_PHOTO_MAIN").exclude(id=resource.id).update(
            tag="LANDING_PHOTO_SECONDARY"
        )

        resource.tag = "LANDING_PHOTO_MAIN"
        resource.save()

        create_notification(
            event=event,
            message=f"{resource.name} has been promoted to the main landing image for {event.title}.",
            notification_type=NotificationTypeChoices.GENERAL,
            metadata={"resource_id": resource.id, "event_id": event.id},
        )

        serializer = ResourceSerializer(resource, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # demote_landing_image  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Demote Landing Image to Secondary",
        description=(
            "Demote the main landing image to secondary. "
            "Only event creators and superusers can demote images."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="resource_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Resource ID of the main image to demote",
                required=True,
            )
        ],
        responses={
            200: ResourceSerializer,
            400: OpenApiResponse(description="Bad request - resource must be the main landing image"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Resource not found"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="demote-landing-image",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def demote_landing_image(self, request, url_safe_title=None):
        event = self.get_object()

        resource_id = request.query_params.get("resource_id")
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if resource.tag != "LANDING_PHOTO_MAIN":
            return Response(
                {"detail": "Resource must be the main landing image (LANDING_PHOTO_MAIN)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resource.tag = "LANDING_PHOTO_SECONDARY"
        resource.save()

        serializer = ResourceSerializer(resource, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # remove_resource  (write)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Remove Resource from Event",
        description=(
            "Remove a resource from the event by its resource ID. "
            "Protected resources cannot be removed. "
            "Only event creators and superusers can remove resources."
        ),
        tags=["Events"],
        parameters=[
            OpenApiParameter(
                name="resource_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Resource ID to remove",
                required=True,
            )
        ],
        responses={
            204: OpenApiResponse(description="Resource removed successfully"),
            400: OpenApiResponse(description="Bad request or resource is protected"),
            403: OpenApiResponse(description="Permission denied"),
            404: OpenApiResponse(description="Resource not found"),
        },
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="remove-resource",
        permission_classes=[IsEventOwnerOrDjangoStaff],
    )
    def remove_resource(self, request, url_safe_title=None):
        event = self.get_object()

        resource_id = request.query_params.get("resource_id")
        if not resource_id:
            return Response(
                {"detail": "resource_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resource = Resource.objects.get(id=resource_id, target_id=event.id)
        except Resource.DoesNotExist:
            return Response(
                {"detail": "Resource not found for this event"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if resource.protected:
            return Response(
                {"detail": "This resource is protected and cannot be deleted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resource_name = resource.name
        resource.delete()

        create_notification(
            event=event,
            message=f"{resource_name} has been removed from {event.title}.",
            notification_type=NotificationTypeChoices.GENERAL,
            metadata={"resource_id": resource_id, "event_id": event.id},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------
    # landing_images  (read)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get Landing Images",
        description=(
            "Retrieve all landing images for the event including both main and secondary images. "
            "Images are tagged as LANDING_PHOTO_MAIN or LANDING_PHOTO_SECONDARY."
        ),
        tags=["Events"],
        responses={200: ResourceSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="landing-images")
    def landing_images(self, request, url_safe_title=None):
        event = self.get_object()
        images = event.landing_images.all()

        page = self.paginate_queryset(images)
        if page is not None:
            serializer = ResourceSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = ResourceSerializer(images, many=True, context={"request": request})
        return Response(serializer.data)
