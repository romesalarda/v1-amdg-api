from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes

from apps.workshops.models.interest import WorkshopInterestSubmission, WorkshopInterestRank
from apps.events.models import Event
from apps.attendee.models import Attendee

class WorkshopInterestRankSerializer(serializers.ModelSerializer):
    """Serializer for a single ranked entry within an interest submission."""

    workshop_title = serializers.CharField(source='workshop.title', read_only=True)

    class Meta:
        model = WorkshopInterestRank
        fields = ('id', 'workshop', 'workshop_title', 'rank')

    def validate_rank(self, value):
        if value < 1:
            raise serializers.ValidationError('Rank must be 1 or greater.')
        return value


class WorkshopInterestSubmissionSerializer(serializers.ModelSerializer):
    """Read serializer for an interest submission including nested ranks."""

    ranks = WorkshopInterestRankSerializer(many=True, read_only=True)
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    attendee = serializers.SlugRelatedField(slug_field='attendee_id', queryset=Attendee.objects.all(), allow_null=True)
    attendee_name = serializers.SerializerMethodField()
    _links = serializers.SerializerMethodField()

    class Meta:
        model = WorkshopInterestSubmission
        fields = (
            'submission_id',
            'event',
            'attendee',
            'attendee_name',
            'submitted_at',
            'updated_at',
            'is_finalised',
            'ranks',
            '_links',
        )
        read_only_fields = ('submission_id', 'submitted_at', 'updated_at')

    @extend_schema_field(OpenApiTypes.STR)
    def get_attendee_name(self, obj):
        return obj.attendee.full_name if obj.attendee_id else None

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'self': {'type': 'string', 'format': 'uri'},
        },
    })
    def get__links(self, obj):
        request = self.context.get('request')
        if not request:
            return {}
        return {
            'self': request.build_absolute_uri(f'/api/workshops/interest-submissions/{obj.pk}/'),
        }


class WorkshopInterestSubmissionCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for creating or updating an interest submission.
    Accepts nested ranks and validates:
    - each workshop belongs to the submission's event
    - ranks are unique within the submission
    """

    ranks = WorkshopInterestRankSerializer(many=True)
    event = serializers.SlugRelatedField(slug_field='event_id', queryset=Event.objects.all())
    attendee = serializers.SlugRelatedField(slug_field='attendee_id', queryset=Attendee.objects.all(), allow_null=True)

    class Meta:
        model = WorkshopInterestSubmission
        fields = ('event', 'attendee', 'ranks')

    def validate(self, attrs):
        event = attrs.get('event') or (self.instance and self.instance.event)
        ranks_data = attrs.get('ranks', [])

        workshop_ids = [r['workshop'].pk for r in ranks_data]
        rank_values = [r['rank'] for r in ranks_data]

        if len(workshop_ids) != len(set(workshop_ids)):
            raise serializers.ValidationError({'ranks': 'Each workshop may only appear once per submission.'})
        if len(rank_values) != len(set(rank_values)):
            raise serializers.ValidationError({'ranks': 'Rank values must be unique within a submission.'})

        if event:
            for rank_entry in ranks_data:
                workshop = rank_entry['workshop']
                if str(workshop.event_id) != str(event.pk):
                    raise serializers.ValidationError(
                        {'ranks': f"Workshop '{workshop.title}' does not belong to the selected event."}
                    )
        return attrs

    def create(self, validated_data):
        ranks_data = validated_data.pop('ranks')
        submission = WorkshopInterestSubmission.objects.create(**validated_data)
        for rank_entry in ranks_data:
            WorkshopInterestRank.objects.create(submission=submission, **rank_entry)
        return submission

    def update(self, instance, validated_data):
        ranks_data = validated_data.pop('ranks', None)
        if instance.is_finalised:
            raise serializers.ValidationError('Cannot update a finalised submission.')
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if ranks_data is not None:
            instance.ranks.all().delete()
            for rank_entry in ranks_data:
                WorkshopInterestRank.objects.create(submission=instance, **rank_entry)
        return instance
