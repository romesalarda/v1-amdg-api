from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from apps.bookings.models import BookingIntent, BookingIntentStatusChoices
from apps.bookings.api.serializers import (
    BookingIntentListSerializer, BookingIntentDetailSerializer, BookingIntentCreateSerializer, BookingIntentUpdateSerializer,
)
from apps.bookings.api.filtersets import BookingIntentFilterSet
from apps.bookings.api.permissions import IsBookingOwnerOrAdministrative
from apps.bookings.api.pagination import StandardPagination

import logging
logger = logging.getLogger(__name__)

@extend_schema_view(
    list=extend_schema(
        summary="List booking intents",
        description="Retrieve a paginated list of booking intents. Users see only their own intents, admins see all.",
        tags=["Booking Intents"],
        parameters=[
            OpenApiParameter(
                name='is_active',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description='Filter by active status (pending and not expired)',
            ),
        ],
    ),
    retrieve=extend_schema(
        summary="Retrieve booking intent details",
        description="Get detailed information about a specific booking intent.",
        tags=["Booking Intents"],
    ),
    create=extend_schema(
        summary="Create booking intent",
        description="Create a new booking intent to reserve capacity for event tickets. Intent expires after 20 minutes.",
        tags=["Booking Intents"],
    ),
    update=extend_schema(
        summary="Update booking intent",
        description="Update an existing booking intent. Only ticket count can be modified and only for pending intents.",
        tags=["Booking Intents"],
    ),
    partial_update=extend_schema(
        summary="Partially update booking intent",
        description="Partially update a booking intent. Only ticket count can be modified and only for pending intents.",
        tags=["Booking Intents"],
    ),
    destroy=extend_schema(
        summary="Delete booking intent",
        description="Delete a booking intent. Only allowed for pending intents.",
        tags=["Booking Intents"],
    ),
)
class BookingIntentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing booking intents.
    
    Booking intents reserve capacity before payment to prevent race conditions.
    They expire after 20 minutes and are cleaned up by background tasks.
    
    Provides:
    - List/Retrieve: Users see their own intents, admins see all
    - Create: Reserve capacity for tickets (max 20 tickets per intent)
    - Update: Modify ticket count (only for pending intents)
    - Cancel: Release reserved capacity
    - Delete: Remove intent (only pending intents)
    
    Permissions:
    - List/Create: Authenticated users
    - Retrieve/Update/Delete/Cancel: Intent creator or administrative staff
    """
    
    queryset = BookingIntent.objects.select_related('event', 'made_by').all()
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingIntentFilterSet
    search_fields = ['booking_intent_id', 'event__title', 'event__display_code']
    ordering_fields = ['created_at', 'expires_at', 'status']
    ordering = ['-created_at']
    lookup_field = 'booking_intent_id'
    
    def get_permissions(self):
        """Set permissions based on action."""
        if self.action in ['list', 'create']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            # For retrieve, update, partial_update, destroy, cancel
            permission_classes = [permissions.IsAuthenticated, IsBookingOwnerOrAdministrative]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        """Filter queryset based on user permissions."""
        queryset = super().get_queryset()
        
        # Non-admin users only see their own intents
        if not self.request.user.is_staff:
            queryset = queryset.filter(made_by=self.request.user)
        
        # Exclude soft-deleted intents from list view
        if self.action == 'list':
            queryset = queryset.filter(deleted_at__isnull=True)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return BookingIntentListSerializer
        elif self.action == 'retrieve':
            return BookingIntentDetailSerializer
        elif self.action == 'create':
            return BookingIntentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return BookingIntentUpdateSerializer
        return BookingIntentDetailSerializer
    
    def get_serializer_context(self):
        """Add event to context for timezone handling."""
        context = super().get_serializer_context()
        if self.action == 'retrieve' and hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                context['event'] = obj.event
            except:
                pass
        return context
    
    def perform_create(self, serializer):
        """Create booking intent with authenticated user."""
        serializer.save(made_by=self.request.user)
    
    def perform_destroy(self, instance):
        """Only allow deletion of pending intents."""
        if instance.status != BookingIntentStatusChoices.PENDING:
            raise ValidationError("Cannot delete a non-pending booking intent.")
        instance.delete()
    
    @extend_schema(
        summary="Cancel booking intent",
        description="Cancel a pending booking intent, releasing the reserved capacity. Cannot be undone.",
        tags=["Booking Intents"],
        request=None,
        responses={
            200: OpenApiResponse(
                description="Intent successfully cancelled",
                response=BookingIntentDetailSerializer
            ),
            400: OpenApiResponse(description="Intent cannot be cancelled (not pending)"),
            404: OpenApiResponse(description="Intent not found"),
        },
        operation_id="bookings_intent_cancel",
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, booking_intent_id=None):
        """Cancel a booking intent."""
        intent = self.get_object()
        
        if intent.status != BookingIntentStatusChoices.PENDING:
            return Response(
                {'detail': 'Only pending intents can be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if intent.is_expired:
            return Response(
                {'detail': 'Cannot cancel an expired intent.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Cancel the intent
        intent.cancel(save=True)
        
        serializer = self.get_serializer(intent)
        return Response(serializer.data)