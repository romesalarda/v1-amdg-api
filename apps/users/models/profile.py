from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from timezone_field import TimeZoneField

from core.utils.validators import PhoneNumberValidator
User = get_user_model()

class EcclesiasticalStatus(models.TextChoices):
    '''
    Ecclesiastical status options for users.
    '''
    CLERGY = 'clergy', _('Clergy')
    RELIGIOUS = 'religious', _('Religious')
    LAITY = 'laity', _('Laity')

class EcclesiasticalRank(models.TextChoices):
    '''
    Ranks for clergy and religious. This is not exhaustive and can be expanded as needed.
    '''
    PRIEST = 'priest', _('Priest')
    DEACON = 'deacon', _('Deacon')
    NUN = 'nun', _('Nun')
    CARDINAL = 'cardinal', _('Cardinal')
    MAJOR_ARCHBISHOP = 'major_archbishop', _('Major Archbishop')
    ARCHBISHOP = 'archbishop', _('Archbishop')
    DIOCESAN_BISHOP = 'diocesan_bishop', _('Diocesan Bishop')
    AUXILIARY_BISHOP = 'auxiliary_bishop', _('Auxiliary Bishop')
    DEAN = 'dean', _('Dean')
    PASTOR = 'pastor', _('Pastor')
    ASSISTANT_PASTOR = 'assistant_pastor', _('Assistant Pastor')
    ASSISTANT_PRIEST = 'assistant_priest', _('Assistant Priest')

    TRANSITIONAL_DEACON = 'transitional_deacon', _('Transitional Deacon')
    PERMANENT_DEACON = 'permanent_deacon', _('Permanent Deacon')

    SISTER = 'sister', _('Sister')
    BROTHER = 'brother', _('Brother')
    ABBOT = 'abbot', _('Abbot')
    ABBESS = 'abbess', _('Abbess')
    MONK = 'monk', _('Monk')
    FRIAR = 'friar', _('Friar')

    OTHER = 'other', _('Other')

class Profile(models.Model):
    '''
    Model representing a user's profile.
    '''
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_name = models.CharField(max_length=100, blank=True)
    profile_picture = models.ImageField(upload_to='profile-pictures/', blank=True, null=True)
    profile_picture_uploaded_at = models.DateTimeField(auto_now_add=True)
    area_from = models.ForeignKey(
        "locations.AreaLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='residents',
        verbose_name=_("Area From"),
        help_text=_("The area where the user is from.")
    )
    contact_phone = models.CharField(max_length=20, blank=True, validators=[PhoneNumberValidator()])
    
    preferred_language = models.CharField(max_length=50, blank=True)
    timezone = TimeZoneField(default='Europe/London')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_public = models.BooleanField(default=True, help_text=_("Whether the profile is visible to others."))
    is_clergy_or_religious = models.BooleanField(default=False, help_text=_("Whether the user is clergy or religious."))
    ecclesiastical_status = models.CharField(
        max_length=20,
        choices=EcclesiasticalStatus.choices,
        blank=True,
        help_text=_("The ecclesiastical status of the user, if applicable.")
    )
    ecclesiastical_rank = models.CharField(
        max_length=20,
        choices=EcclesiasticalRank.choices,
        blank=True,
        help_text=_("The ecclesiastical rank of the user, if applicable.")
    )

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def __repr__(self):
        return f"<Profile(user={self.user.username}, preferred_name={self.preferred_name})>"
    
    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"
        ordering = ['-created_at']

    @property
    def full_name(self):
        return f"{self.user.first_name} {self.user.last_name}".strip()
    
    def save(self, *args, **kwargs):
        self.full_clean()
        self.preferred_name = self.preferred_name.title()
        super().save(*args, **kwargs)

