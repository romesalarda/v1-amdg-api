from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
import uuid

User = get_user_model()


class LeaderLocationType(models.TextChoices):
    COUNTRY = 'country', 'Country'
    CLUSTER = 'cluster', 'Cluster'
    CHAPTER = 'chapter', 'Chapter'
    AREA = 'area', 'Area'


class Leader(models.Model):
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='authorities_led')
    
    target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    target_id = models.PositiveIntegerField()
    authority_object = GenericForeignKey('target_type', 'target_id')
    
    notes = models.TextField(blank=True)
    
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='leaders_added')
    updated_at = models.DateTimeField(auto_now=True)

    organisation = models.ForeignKey('organisations.Organisation', on_delete=models.CASCADE, related_name='organisation_leaders', null=True, blank=True)
    
    class Meta:
        unique_together = ('user', 'target_type', 'target_id')

    @staticmethod
    def _location_type_to_model_name(location_type: str) -> str | None:
        mapping = {
            LeaderLocationType.COUNTRY: 'countrylocation',
            LeaderLocationType.CLUSTER: 'clusterlocation',
            LeaderLocationType.CHAPTER: 'chapterlocation',
            LeaderLocationType.AREA: 'arealocation',
        }
        return mapping.get(location_type)

    @staticmethod
    def _model_name_to_location_type(model_name: str) -> str | None:
        mapping = {
            'countrylocation': LeaderLocationType.COUNTRY,
            'clusterlocation': LeaderLocationType.CLUSTER,
            'chapterlocation': LeaderLocationType.CHAPTER,
            'arealocation': LeaderLocationType.AREA,
        }
        return mapping.get(model_name)

    @classmethod
    def filter_by_location(cls, queryset, location_type: str, location_id: int):
        model_name = cls._location_type_to_model_name(location_type)
        if not model_name:
            return queryset.none()
        try:
            content_type = ContentType.objects.get(model=model_name)
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(target_type=content_type, target_id=location_id)

    def set_location_target(self, location_type: str, location_id: int) -> None:
        model_name = self._location_type_to_model_name(location_type)
        if not model_name:
            raise ValidationError('Invalid location type.')
        content_type = ContentType.objects.get(model=model_name)
        self.target_type = content_type
        self.target_id = location_id

    @property
    def location_type(self) -> str | None:
        if not self.target_type:
            return None
        return self._model_name_to_location_type(self.target_type.model)

    @property
    def location_id(self) -> int:
        return self.target_id

    @property
    def location_name(self) -> str:
        if self.authority_object:
            return str(self.authority_object)
        return 'Unknown'

    def clean(self):
        if self.target_type and self._model_name_to_location_type(self.target_type.model) is None:
            raise ValidationError('Leaders can only target country, cluster, chapter, or area locations.')
    
    def __str__(self):
        if self.organisation:
            return f"{self.user.username} leads {self.organisation.title}"
        return f"{self.user.username} leads {self.authority_object}"


class LocationLeaderInvite(models.Model):
    """Invite a user to become a leader for a specific location within an organisation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        'organisations.Organisation',
        on_delete=models.CASCADE,
        related_name='leader_invites',
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leader_invites_received',
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='leader_invites_sent',
    )

    location_type = models.CharField(max_length=20, choices=LeaderLocationType.choices)
    location_id = models.PositiveIntegerField()
    notes = models.TextField(blank=True)

    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'target_user', 'location_type', 'location_id'],
                condition=Q(is_active=True, accepted=False),
                name='uniq_active_pending_location_leader_invite',
            ),
        ]
        indexes = [
            models.Index(fields=['organisation', 'location_type', 'location_id']),
            models.Index(fields=['target_user', 'is_active', 'accepted']),
        ]

    @property
    def is_valid(self):
        if not self.is_active:
            return False
        if self.accepted:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def accept_invite(self, accepted_by=None):
        if not self.is_valid:
            raise ValidationError('Invite is not valid.')

        if accepted_by and self.target_user and accepted_by != self.target_user:
            raise ValidationError('Only the invite target user can accept this invite.')

        if not self.target_user:
            raise ValidationError('Invite target user is required to accept invite.')

        existing = Leader.filter_by_location(
            Leader.objects.filter(user=self.target_user),
            self.location_type,
            self.location_id,
        ).filter(organisation=self.organisation)

        if existing.exists():
            leader = existing.first()
        else:
            leader = Leader(
                user=self.target_user,
                organisation=self.organisation,
                notes=self.notes,
                added_by=self.invited_by,
            )
            leader.set_location_target(self.location_type, self.location_id)
            leader.full_clean()
            leader.save()

        self.accepted = True
        self.accepted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=['accepted', 'accepted_at', 'is_active'])
        return leader

    def __str__(self):
        return (
            f"Leader invite for {self.target_user} in {self.organisation} "
            f"({self.location_type}:{self.location_id})"
        )