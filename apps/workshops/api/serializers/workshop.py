from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from apps.workshops.models.workshop import Workshop, WorkshopStatus, AllocationMode
from apps.attendee.models import Attendee
from apps.events.models import Event
class WorkshopListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing workshops."""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    allocation_mode_display = serializers.CharField(source='get_allocation_mode_display', read_only=True)
    registration_count = serializers.SerializerMethodField()
    is_full = serializers.BooleanField(read_only=True)
    _links = serializers.SerializerMethodField()

    class Meta:
        model = Workshop
        fields = (
            'id',
            'title',
            'event',
            'date',
            'landing_image',
            'status',
            'status_display',
            'allocation_mode',
            'allocation_mode_display',
            'capacity',
            'registration_count',
            'is_full',
            'duration_minutes',
            'registration_opens_at',
            'registration_closes_at',
            '_links',
        )
        read_only_fields = ('id',)

    @extend_schema_field(OpenApiTypes.INT)
    def get_registration_count(self, obj):
        return obj.current_registration_count

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'registrations': {'type': 'string', 'format': 'uri'},
        },
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        base = request.build_absolute_uri(f'/api/workshops/workshops/{obj.pk}/')
        return {
            'self': base,
            'registrations': request.build_absolute_uri(f'/api/workshops/workshops/{obj.pk}/registrations/'),
        }


class WorkshopDetailSerializer(WorkshopListSerializer):
    """Full detail serializer for a single workshop."""

    venue_name = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    class Meta(WorkshopListSerializer.Meta):
        fields = WorkshopListSerializer.Meta.fields + (
            'description',
            'what_to_expect',
            'what_to_bring',
            'notes',
            'venue',
            'venue_name',
            'room',
            'room_name',
            'verification_status',
        )

    @extend_schema_field(OpenApiTypes.STR)
    def get_venue_name(self, obj):
        return str(obj.venue) if obj.venue else None

    @extend_schema_field(OpenApiTypes.STR)
    def get_room_name(self, obj):
        return str(obj.room) if obj.room else None


class WorkshopCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating workshops."""

    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())

    class Meta:
        model = Workshop
        fields = (
            'title',
            'description',
            'landing_image',
            'what_to_expect',
            'what_to_bring',
            'event',
            'date',
            'venue',
            'room',
            'notes',
            'status',
            'allocation_mode',
            'capacity',
            'duration_minutes',
            'registration_opens_at',
            'registration_closes_at',
        )

    def validate(self, attrs):
        opens = attrs.get('registration_opens_at') or (self.instance and self.instance.registration_opens_at)
        closes = attrs.get('registration_closes_at') or (self.instance and self.instance.registration_closes_at)
        if opens and closes and opens >= closes:
            raise serializers.ValidationError(
                {'registration_closes_at': 'Registration must close after it opens.'}
            )
        return attrs
