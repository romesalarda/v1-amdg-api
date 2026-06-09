from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from apps.workshops.models.registration import WorkshopRegistration, WorkshopRegistrationStatus


class WorkshopRegistrationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing workshop registrations."""

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    attendee_name = serializers.SerializerMethodField()
    _links = serializers.SerializerMethodField()

    class Meta:
        model = WorkshopRegistration
        fields = (
            'registration_id',
            'booking_reference',
            'workshop',
            'attendee',
            'attendee_name',
            'status',
            'status_display',
            'allocation_method',
            'registered_at',
            '_links',
        )
        read_only_fields = ('registration_id', 'booking_reference', 'registered_at')

    @extend_schema_field(OpenApiTypes.STR)
    def get_attendee_name(self, obj):
        return obj.attendee.full_name if obj.attendee_id else None

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
            'workshop': {'type': 'string', 'format': 'uri'},
        },
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        return {
            'self': request.build_absolute_uri(f'/api/workshops/registrations/{obj.pk}/'),
            'workshop': request.build_absolute_uri(f'/api/workshops/workshops/{obj.workshop_id}/'),
        }


class WorkshopRegistrationDetailSerializer(WorkshopRegistrationListSerializer):
    """Full detail serializer for a single workshop registration."""

    allocated_by_name = serializers.SerializerMethodField()

    class Meta(WorkshopRegistrationListSerializer.Meta):
        fields = WorkshopRegistrationListSerializer.Meta.fields + (
            'notes',
            'allocated_by',
            'allocated_by_name',
            'verification_status',
        )

    @extend_schema_field(OpenApiTypes.STR)
    def get_allocated_by_name(self, obj):
        return str(obj.allocated_by) if obj.allocated_by_id else None


class WorkshopRegistrationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new workshop registration."""

    class Meta:
        model = WorkshopRegistration
        fields = (
            'workshop',
            'attendee',
            'status',
            'notes',
        )

    def validate(self, attrs):
        workshop = attrs.get('workshop')
        attendee = attrs.get('attendee')
        if workshop and attendee:
            if WorkshopRegistration.objects.filter(workshop=workshop, attendee=attendee).exists():
                raise serializers.ValidationError(
                    'This attendee is already registered for this workshop.'
                )
        return attrs
