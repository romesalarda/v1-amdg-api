from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from apps.workshops.models.staff import WorkshopStaff, WorkshopStaffRoleChoice


class WorkshopStaffSerializer(serializers.ModelSerializer):
    """Full serializer for a workshop staff assignment."""

    role_display = serializers.CharField(source='get_role_display', read_only=True)
    staff_name = serializers.SerializerMethodField()
    _links = serializers.SerializerMethodField()

    class Meta:
        model = WorkshopStaff
        fields = (
            'id',
            'workshop',
            'event_staff',
            'staff_name',
            'role',
            'role_display',
            'notes',
            'added_at',
            'added_by',
            '_links',
        )
        read_only_fields = ('id', 'added_at')

    @extend_schema_field(OpenApiTypes.STR)
    def get_staff_name(self, obj):
        return str(obj.event_staff) if obj.event_staff_id else None

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
            'self': request.build_absolute_uri(f'/api/workshops/staff/{obj.pk}/'),
            'workshop': request.build_absolute_uri(f'/api/workshops/workshops/{obj.workshop_id}/'),
        }


class WorkshopStaffCreateSerializer(serializers.ModelSerializer):
    """Write serializer for assigning staff to a workshop."""

    class Meta:
        model = WorkshopStaff
        fields = ('workshop', 'event_staff', 'role', 'notes')

    def validate(self, attrs):
        workshop = attrs.get('workshop')
        event_staff = attrs.get('event_staff')
        if workshop and event_staff:
            if str(event_staff.event_id) != str(workshop.event_id):
                raise serializers.ValidationError(
                    'Event staff member must belong to the same event as the workshop.'
                )
        return attrs
