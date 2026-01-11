"""
URL configuration for the bookings app.

Provides comprehensive routing with nested resources:
- /api/bookings/ - Main booking endpoints
- /api/bookings/{id}/attendees/ - Nested attendees for specific booking
- /api/bookings/{id}/tickets/ - Nested tickets for specific booking
- /api/bookings/packages/ - Booking packages
- /api/bookings/ticket-types/ - Ticket types
- /api/bookings/tickets/ - All tickets (read-only)
- /api/bookings/alternative-signins/ - Event alternative signins (admin only)
- /api/bookings/attendee-alternative-signins/ - Attendee alternative signins (admin only)

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.bookings.api.viewsets import (
    BookingViewSet,
    BookingIntentViewSet,
    TicketTypeViewSet,
    TicketViewSet,
    BookingPackageViewSet,
    EventAlternativeSigninViewSet,
    AttendeeAlternativeSigninViewSet,
)

app_name = 'bookings'

# Create separate routers to avoid path conflicts
booking_router = DefaultRouter()
booking_router.register(r'list', BookingViewSet, basename='booking')

intent_router = DefaultRouter()
intent_router.register(r'intents', BookingIntentViewSet, basename='bookingintent')

package_router = DefaultRouter()
package_router.register(r'packages', BookingPackageViewSet, basename='bookingpackage')

ticket_type_router = DefaultRouter()
ticket_type_router.register(r'ticket-types', TicketTypeViewSet, basename='tickettype')

ticket_router = DefaultRouter()
ticket_router.register(r'tickets', TicketViewSet, basename='ticket')

signin_router = DefaultRouter()
signin_router.register(r'alternative-signins', EventAlternativeSigninViewSet, basename='eventalternativesignin')

attendee_signin_router = DefaultRouter()
attendee_signin_router.register(r'attendee-alternative-signins', AttendeeAlternativeSigninViewSet, basename='attendeealternativesignin')

urlpatterns = [
    path('', include(booking_router.urls)),
    path('', include(intent_router.urls)),
    path('', include(package_router.urls)),
    path('', include(ticket_type_router.urls)),
    path('', include(ticket_router.urls)),
    path('', include(signin_router.urls)),
    path('', include(attendee_signin_router.urls)),
]
