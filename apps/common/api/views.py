from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from zoneinfo import available_timezones
from drf_spectacular.utils import extend_schema, OpenApiParameter


class TimezoneListView(APIView):
    """
    Returns a sorted list of all available IANA timezones.
    Optionally filter results with ?search=<query>.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='search',
                type=str,
                location=OpenApiParameter.QUERY,
                description='Case-insensitive substring filter on timezone names.',
                required=False,
            )
        ],
        responses={200: {'type': 'array', 'items': {'type': 'string'}}},
        summary='List available timezones',
        tags=['Utils'],
    )
    def get(self, request):
        timezones = sorted(available_timezones())
        search = request.query_params.get('search', '').strip().lower()
        if search:
            timezones = [tz for tz in timezones if search in tz.lower()]
        return Response(timezones)
