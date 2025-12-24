from django.db import models
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from django.utils.text import slugify
from django.core import validators

import uuid


class GeneralSectorType(models.TextChoices):
    EUROPE = "EUROPE", _("Europe")
    ASIA = "ASIA", _("Asia")
    NORTH_AMERICA = "NORTH_AMERICA", _("North America")
    CENTRAL_AMERICA = "CENTRAL_AMERICA", _("Central America")
    SOUTH_AMERICA = "SOUTH_AMERICA", _("South America")
    AFRICA = "AFRICA", _("Africa")
    OCEANIA = "OCEANIA", _("Oceania")
    MIDDLE_EAST = "MIDDLE_EAST", _("Middle East")

class SpecificSectorType(models.TextChoices):
    # --- Europe ---
    NORTH_EUROPE = "NORTH_EUROPE", _("Northern Europe")
    SOUTH_EUROPE = "SOUTH_EUROPE", _("Southern Europe")
    WEST_EUROPE = "WEST_EUROPE", _("Western Europe")
    EAST_EUROPE = "EAST_EUROPE", _("Eastern Europe")
    CENTRAL_EUROPE = "CENTRAL_EUROPE", _("Central Europe")

    # --- Asia ---
    EAST_ASIA = "EAST_ASIA", _("East Asia")
    SOUTH_ASIA = "SOUTH_ASIA", _("South Asia")
    SOUTHEAST_ASIA = "SOUTHEAST_ASIA", _("Southeast Asia")
    CENTRAL_ASIA = "CENTRAL_ASIA", _("Central Asia")
    WEST_ASIA = "WEST_ASIA", _("Western Asia")  # overlaps with Middle East

    # --- Americas ---
    NORTH_AMERICA = "NORTH_AMERICA", _("North America")
    CENTRAL_AMERICA = "CENTRAL_AMERICA", _("Central America")
    CARIBBEAN = "CARIBBEAN", _("Caribbean")
    SOUTH_AMERICA_NORTH = "SOUTH_AMERICA_NORTH", _("Northern South America")
    SOUTH_AMERICA_SOUTH = "SOUTH_AMERICA_SOUTH", _("Southern South America")
    ANDES = "ANDES", _("Andean Region")
    CONO_SUR = "CONO_SUR", _("Cono Sur (Southern Cone)")

    # --- Africa ---
    NORTH_AFRICA = "NORTH_AFRICA", _("North Africa")
    WEST_AFRICA = "WEST_AFRICA", _("West Africa")
    EAST_AFRICA = "EAST_AFRICA", _("East Africa")
    CENTRAL_AFRICA = "CENTRAL_AFRICA", _("Central Africa")
    SOUTH_AFRICA = "SOUTH_AFRICA", _("Southern Africa")

    # --- Oceania ---
    AUSTRALIA_NEWZEALAND = "AUSTRALIA_NEWZEALAND", _("Australia & New Zealand")
    MELANESIA = "MELANESIA", _("Melanesia")
    MICRONESIA = "MICRONESIA", _("Micronesia")
    POLYNESIA = "POLYNESIA", _("Polynesia")

    # --- Middle East (can also overlap with West Asia) ---
    GULF = "GULF", _("Gulf States")
    LEVANT = "LEVANT", _("Levant")
    PERSIAN = "PERSIAN", _("Persian Region")
        
class CountryLocation (models.Model):
    
    '''
    specific country internationally
    '''
    country = CountryField(blank=True, null=True, unique=True) # only one country in the database
    general_sector = models.CharField(verbose_name="general world sector", choices=GeneralSectorType)
    specific_sector = models.CharField(verbose_name="specific world sector", choices=SpecificSectorType)
    date_added = models.DateField(auto_now_add=True)
    active = models.BooleanField(verbose_name="is-active-country", default=True)
    
    def __str__(self):
        return f"{self.general_sector} -> {self.specific_sector} -> {self.country}"
    
class ClusterLocation (models.Model):
    
    cluster_name = models.CharField(verbose_name="name-of-cluster", max_length=150) # verbose and nice name
    cluster_code = models.CharField(verbose_name="cluster-code", max_length=3, unique=True, null=True) # for id purposes
    
    country = models.ForeignKey(CountryLocation, on_delete=models.CASCADE, related_name="clusters")
    
    description = models.TextField(blank=True, null=True)
    active = models.BooleanField(verbose_name="is-active-cluster", default=True)
    established_date = models.DateField(verbose_name="established-date", blank=True, null=True
                                        , auto_now_add=True)
    
    date_added = models.DateField(auto_now_add=True)
    date_updated = models.DateField(auto_now=True)
    
    def save(self, *args, **kwargs):
        if not self.cluster_code:
            self.cluster_code = str(self.cluster_name[:3]).upper()
        self.cluster_name = slugify(self.cluster_name).capitalize().strip()
        return super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.country} -> {self.cluster_name}"
  
        
class ChapterLocation (models.Model):
    '''
    specific chapter - chapter head - general mass area
    '''    
    chapter_name = models.CharField(verbose_name="name-of-chapter", max_length=150) # verbose and nice name
    chapter_code = models.CharField(verbose_name="chapter-code", max_length=3, null=True) # for id purposes
    
    cluster = models.ForeignKey(ClusterLocation, on_delete=models.CASCADE, related_name="chapters")
    
    description = models.TextField(blank=True, null=True, help_text="description of the chapter location", max_length=400)    
    active = models.BooleanField(verbose_name="is-active-chapter", default=True)
    established_date = models.DateField(verbose_name="established-date", blank=True, null=True, auto_now_add=True)
    
    date_added = models.DateField(auto_now_add=True)
    date_updated = models.DateField(auto_now=True)

    class Meta:
        unique_together = ("chapter_name", "cluster")
        
    def save(self, *args, **kwargs):
        if self.chapter_code is None:
            self.chapter_code = str(self.chapter_name[:3]).upper()
        self.chapter_name = slugify(self.chapter_name).capitalize().strip()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.cluster} -> {self.chapter_name}"

    
class AreaLocation (models.Model):
    '''
    Specific area - area head (smallest unit of location)
    
    Generally represents an Area where events are regularly held.
    '''
    area_id = models.UUIDField(default=uuid.uuid4, editable=False) # human unreadable id
    area_name = models.CharField(verbose_name="name-of-area", max_length=150) # verbose and nice name
    area_code = models.CharField(verbose_name="area-code", max_length=3, unique=True, null=True) # for id purposes
    chapter = models.ForeignKey(ChapterLocation, on_delete=models.CASCADE, related_name="areas")
    description = models.TextField(blank=True, null=True, help_text="description of the area location", max_length=400)
    active = models.BooleanField(verbose_name="is-active-area", default=True)
    established_date = models.DateField(verbose_name="established-date", blank=True, null=True, auto_now_add=True)

    date_added = models.DateField(auto_now_add=True)
    date_updated = models.DateField(auto_now=True)

    class Meta:
        unique_together = ("area_name", "chapter")
        
    def save(self, *args, **kwargs):
        if self.area_code is None:
            self.area_code = str(self.area_name[:3]).upper()
        self.area_name = slugify(self.area_name).capitalize().strip()
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.chapter} -> {self.area_name}"
    
class RelativeArea(models.Model):
    
    name = models.CharField(verbose_name=_("name of relative location"), max_length=100) 
    relative_area = models.ForeignKey(AreaLocation, on_delete=models.SET_NULL, null=True, related_name="relative_search_areas")
    
    def save(self, *args, **kwargs):
        self.name = slugify(self.name).capitalize().strip()
        return super().save(*args, **kwargs)
