"""
EventSponsorActionsMixin — sponsorship actions for EventViewSet.
"""
from __future__ import annotations

from django.db.models import Q, Count
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.api.serializers import SponsorableEventListSerializer
from apps.events.api.permissions import (
    IsEventAdminOrDjangoStaff,
    CanManageSponsorForOrganisation,
)
from apps.organisations.models import EventSponsor, EventSponsorPackage
from apps.organisations.api.serializers import (
    EventSponsorListSerializer,
    EventSponsorDetailSerializer,
    EventSponsorCreateUpdateSerializer,
    EventSponsorPackageListSerializer,
    EventSponsorPackageDetailSerializer,
    EventSponsorPackageCreateUpdateSerializer,
)


_SPONSOR_SELECT_RELATED = (
    "organisation",
    "event",
    "package",
    "added_by",
    "verified_by",
    "processed_by",
)


class EventSponsorActionsMixin:
    """Mixin providing sponsorship @actions for EventViewSet."""

    # ------------------------------------------------------------------
    # sponsorable  (detail=False)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Get sponsorable events",
        description=(
            "Retrieve events available for sponsorship checkout. "
            "Results are limited to events with sponsorships enabled and at "
            "least one active sponsorship package."
        ),
        tags=["Events"],
        responses={200: SponsorableEventListSerializer(many=True)},
        parameters=[
            OpenApiParameter(name="search", type=OpenApiTypes.STR, description="Search by title, description, or display code."),
            OpenApiParameter(name="page", type=OpenApiTypes.INT, description="Page number."),
            OpenApiParameter(name="page_size", type=OpenApiTypes.INT, description="Number of results per page."),
        ],
    )
    @action(detail=False, methods=["get"], url_path="sponsorable")
    def sponsorable(self, request):
        queryset = (
            self.get_queryset()
            .filter(
                settings__accepting_sponsorships_enabled=True,
                sponsorship_packages__active=True,
            )
            .annotate(
                active_sponsorship_packages_count=Count(
                    "sponsorship_packages",
                    filter=Q(sponsorship_packages__active=True),
                    distinct=True,
                )
            )
            .distinct()
        )

        search_value = request.query_params.get("search")
        if search_value:
            queryset = queryset.filter(
                Q(title__icontains=search_value)
                | Q(short_description__icontains=search_value)
                | Q(long_description__icontains=search_value)
                | Q(display_code__icontains=search_value)
            )

        page = self.paginate_queryset(queryset)
        serializer = SponsorableEventListSerializer(
            page if page is not None else queryset,
            many=True,
            context={"request": request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # sponsors  (GET list / POST create)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Event Sponsors",
        description="List sponsors for an event or create a sponsor for the event.",
        tags=["Events", "Event Sponsors"],
    )
    @extend_schema(methods=["get"], operation_id="event_list_sponsors_list")
    @extend_schema(methods=["post"], operation_id="event_list_sponsors_create")
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="sponsors",
        permission_classes=[CanManageSponsorForOrganisation],
    )
    def sponsors(self, request, url_safe_title=None):
        event = self.get_object()
        queryset = EventSponsor.objects.select_related(*_SPONSOR_SELECT_RELATED).filter(
            event=event
        )

        if request.method == "GET":
            page = self.paginate_queryset(queryset)
            serializer = EventSponsorListSerializer(
                page if page is not None else queryset,
                many=True,
                context={"request": request},
            )
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        # POST
        payload = request.data.copy()
        payload.setdefault("event", event.id)

        serializer = EventSponsorCreateUpdateSerializer(
            data=payload,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        organisation = serializer.validated_data.get("organisation")
        if not organisation:
            return Response(
                {"organisation_id": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not CanManageSponsorForOrganisation.user_can_manage_for_organisation(
            request.user, event, organisation
        ):
            return Response(
                {"detail": "You don't have permission to create a sponsor for this organisation."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if serializer.validated_data.get("event") != event:
            return Response(
                {"event_id": ["Event in payload must match URL event_id."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sponsor = serializer.save()
        return Response(
            EventSponsorDetailSerializer(sponsor, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------------
    # sponsor_detail  (GET / PATCH / DELETE)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Event Sponsor Detail",
        description="Retrieve, update, or delete a sponsor within an event context.",
        parameters=[
            OpenApiParameter(
                name="sponsor_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                required=True,
            ),
        ],
        tags=["Events", "Event Sponsors"],
    )
    @extend_schema(methods=["get"], operation_id="event_list_sponsors_retrieve")
    @extend_schema(methods=["patch"], operation_id="event_list_sponsors_partial_update")
    @extend_schema(methods=["delete"], operation_id="event_list_sponsors_destroy")
    @action(
        detail=True,
        methods=["get", "patch", "delete"],
        url_path=r"sponsors/(?P<sponsor_id>[^/.]+)",
        permission_classes=[CanManageSponsorForOrganisation],
    )
    def sponsor_detail(self, request, url_safe_title=None, sponsor_id=None):
        event = self.get_object()
        sponsor = get_object_or_404(
            EventSponsor.objects.select_related(*_SPONSOR_SELECT_RELATED),
            sponsor_id=sponsor_id,
            event=event,
        )

        if request.method == "GET":
            serializer = EventSponsorDetailSerializer(sponsor, context={"request": request})
            return Response(serializer.data)

        # Write path — org-level permission check
        if not CanManageSponsorForOrganisation.user_can_manage_for_organisation(
            request.user, event, sponsor.organisation
        ):
            return Response(
                {"detail": "You don't have permission to manage this sponsor."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == "DELETE":
            sponsor.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        payload = request.data.copy()
        payload.setdefault("event", event.id)

        serializer = EventSponsorCreateUpdateSerializer(
            sponsor,
            data=payload,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        payload_event = serializer.validated_data.get("event")
        if payload_event and payload_event != event:
            return Response(
                {"event_id": ["Event in payload must match URL event_id."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sponsor = serializer.save()
        return Response(EventSponsorDetailSerializer(sponsor, context={"request": request}).data)

    # ------------------------------------------------------------------
    # approve_sponsor
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Approve Event Sponsor",
        description="Mark a sponsor as verified. Event admin permissions required.",
        parameters=[
            OpenApiParameter(
                name="sponsor_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                required=True,
            ),
        ],
        operation_id="event_list_sponsors_approve",
        tags=["Events", "Event Sponsors"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"sponsors/(?P<sponsor_id>[^/.]+)/approve",
        permission_classes=[IsEventAdminOrDjangoStaff],
    )
    def approve_sponsor(self, request, url_safe_title=None, sponsor_id=None):
        event = self.get_object()
        sponsor = get_object_or_404(
            EventSponsor.objects.select_related(*_SPONSOR_SELECT_RELATED),
            sponsor_id=sponsor_id,
            event=event,
        )
        sponsor.mark_verified(verifier=request.user)
        serializer = EventSponsorDetailSerializer(sponsor, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # reject_sponsor
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Reject Event Sponsor",
        description="Mark a sponsor as rejected. Event admin permissions required.",
        parameters=[
            OpenApiParameter(
                name="sponsor_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                required=True,
            ),
        ],
        operation_id="event_list_sponsors_reject",
        tags=["Events", "Event Sponsors"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"sponsors/(?P<sponsor_id>[^/.]+)/reject",
        permission_classes=[IsEventAdminOrDjangoStaff],
    )
    def reject_sponsor(self, request, url_safe_title=None, sponsor_id=None):
        event = self.get_object()
        sponsor = get_object_or_404(
            EventSponsor.objects.select_related(*_SPONSOR_SELECT_RELATED),
            sponsor_id=sponsor_id,
            event=event,
        )
        sponsor.mark_rejected(verifier=request.user)
        serializer = EventSponsorDetailSerializer(sponsor, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # sponsorship_packages  (GET list / POST create)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Event Sponsorship Packages",
        description="List or create sponsor packages for an event.",
        tags=["Events", "Sponsorship Packages"],
    )
    @extend_schema(methods=["get"], operation_id="event_list_sponsorship_packages_list")
    @extend_schema(methods=["post"], operation_id="event_list_sponsorship_packages_create")
    @action(
        detail=True,
        methods=["get", "post"],
        url_path="sponsorship-packages",
        permission_classes=[IsEventAdminOrDjangoStaff],
    )
    def sponsorship_packages(self, request, url_safe_title=None):
        event = self.get_object()

        if request.method == "GET":
            queryset = EventSponsorPackage.objects.select_related("event").filter(event=event)
            page = self.paginate_queryset(queryset)
            serializer = EventSponsorPackageListSerializer(
                page if page is not None else queryset,
                many=True,
                context={"request": request},
            )
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        payload = request.data.copy()
        payload.setdefault("event", event.id)
        serializer = EventSponsorPackageCreateUpdateSerializer(
            data=payload, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("event") != event:
            return Response(
                {"event_id": ["Event in payload must match URL event_id."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        package = serializer.save()
        return Response(
            EventSponsorPackageDetailSerializer(package, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------------
    # sponsorship_package_detail  (GET / PATCH / DELETE)
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Event Sponsorship Package Detail",
        description="Retrieve, update, or delete a sponsorship package for an event.",
        parameters=[
            OpenApiParameter(
                name="package_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                required=True,
            ),
        ],
        tags=["Events", "Sponsorship Packages"],
    )
    @extend_schema(methods=["get"], operation_id="event_list_sponsorship_packages_retrieve")
    @extend_schema(methods=["patch"], operation_id="event_list_sponsorship_packages_partial_update")
    @extend_schema(methods=["delete"], operation_id="event_list_sponsorship_packages_destroy")
    @action(
        detail=True,
        methods=["get", "patch", "delete"],
        url_path=r"sponsorship-packages/(?P<package_id>[^/.]+)",
        permission_classes=[IsEventAdminOrDjangoStaff],
    )
    def sponsorship_package_detail(self, request, url_safe_title=None, package_id=None):
        event = self.get_object()
        package = get_object_or_404(
            EventSponsorPackage.objects.select_related("event"),
            package_id=package_id,
            event=event,
        )

        if request.method == "GET":
            serializer = EventSponsorPackageDetailSerializer(package, context={"request": request})
            return Response(serializer.data)

        if request.method == "DELETE":
            if package.payment is not None:
                return Response(
                    {"detail": "Cannot delete a package that already has an associated payment."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            package.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        payload = request.data.copy()
        payload.setdefault("event", event.id)

        serializer = EventSponsorPackageCreateUpdateSerializer(
            package,
            data=payload,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        payload_event = serializer.validated_data.get("event")
        if payload_event and payload_event != event:
            return Response(
                {"event_id": ["Event in payload must match URL event_id."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        package = serializer.save()
        return Response(EventSponsorPackageDetailSerializer(package, context={"request": request}).data)

    # ------------------------------------------------------------------
    # public_sponsors
    # ------------------------------------------------------------------

    @extend_schema(
        summary="Public Event Sponsors",
        description="List approved sponsors visible on the event landing page.",
        tags=["Events", "Event Sponsors"],
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="public-sponsors",
        permission_classes=[permissions.AllowAny],
    )
    def public_sponsors(self, request, url_safe_title=None):
        event = self.get_object()
        queryset = EventSponsor.objects.select_related(
            "organisation", "event", "package"
        ).filter(event=event, approval_status="APPROVED", show_on_landing=True)
        serializer = EventSponsorListSerializer(queryset, many=True, context={"request": request})
        return Response(serializer.data)
