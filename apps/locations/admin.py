from django.contrib import admin
from .models import (
    CountryLocation, ClusterLocation, ChapterLocation, AreaLocation, RelativeArea,
    POI, Venue, RoomVenue, VenueContact, VenueMetadata, FloorPlan, FloorPlanAnnotation, FloorPlanAnnotationMetadata
)


@admin.register(CountryLocation)
class CountryLocationAdmin(admin.ModelAdmin):
    list_display = ('country', 'general_sector', 'specific_sector', 'active', 'date_added')
    list_filter = ('general_sector', 'specific_sector', 'active', 'date_added')
    search_fields = ('country',)
    readonly_fields = ('date_added',)
    
    fieldsets = (
        ('Location Information', {
            'fields': ('country', 'general_sector', 'specific_sector', 'active', 'longitude', 'latitude')
        }),
        ('Metadata', {
            'fields': ('date_added',),
            'classes': ('collapse',)
        }),
    )



@admin.register(FloorPlan)
class FloorPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'venue', 'event_venue', 'added_at', 'added_by')
    list_filter = ('added_at',)
    search_fields = ('name', 'description', 'venue__poi__name')
    readonly_fields = ('added_at', 'updated_at')
    
    fieldsets = (
        ('Floor Plan Information', {
            'fields': ('venue', 'name', 'description', 'event_venue', 'level', 'level_label', 
                       'original_width', 'original_height',
                       )
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(FloorPlanAnnotation)
class FloorPlanAnnotationAdmin(admin.ModelAdmin):
    list_display = ('floor_plan', 'room_venue', 'added_at', 'added_by')
    list_filter = ('room_venue', 'added_at')
    search_fields = ('description', 'floor_plan__name')
    readonly_fields = ('added_at', 'updated_at')
    
    fieldsets = (
        ('Annotation Information', {
            'fields': ('floor_plan', 'annotation_type', 'description', 'coordinates', 'room_venue', 'vertices', 'colour')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(FloorPlanAnnotationMetadata)
class FloorPlanAnnotationMetadataAdmin(admin.ModelAdmin):
    list_display = ('annotation', 'label', 'value', 'added_at', 'added_by')
    list_filter = ('label', 'added_at')
    search_fields = ('label', 'value', 'annotation__description')
    readonly_fields = ('added_at',)
    
    fieldsets = (
        ('Annotation Metadata Information', {
            'fields': ('annotation', 'label', 'value')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', ),
            'classes': ('collapse',)
        }),
    )

@admin.register(ClusterLocation)
class ClusterLocationAdmin(admin.ModelAdmin):
    list_display = ('cluster_name', 'cluster_code', 'country', 'active', 'established_date')
    list_filter = ('active', 'country', 'established_date', 'date_added')
    search_fields = ('cluster_name', 'cluster_code', 'description')
    readonly_fields = ('date_added', 'date_updated')
    
    fieldsets = (
        ('Cluster Information', {
            'fields': ('cluster_name', 'cluster_code', 'country', 'description', 'active', 'longitude', 'latitude')
        }),
        ('Dates', {
            'fields': ('established_date', 'date_added', 'date_updated'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ChapterLocation)
class ChapterLocationAdmin(admin.ModelAdmin):
    list_display = ('chapter_name', 'chapter_code', 'cluster', 'active', 'established_date')
    list_filter = ('active', 'cluster__country', 'established_date', 'date_added')
    search_fields = ('chapter_name', 'chapter_code', 'description', 'cluster__cluster_name')
    readonly_fields = ('date_added', 'date_updated')
    autocomplete_fields = ['cluster']
    
    fieldsets = (
        ('Chapter Information', {
            'fields': ('chapter_name', 'chapter_code', 'cluster', 'description', 'active', 'longitude', 'latitude')
        }),
        ('Dates', {
            'fields': ('established_date', 'date_added', 'date_updated'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AreaLocation)
class AreaLocationAdmin(admin.ModelAdmin):
    list_display = ('area_name', 'area_code', 'chapter', 'active', 'established_date')
    list_filter = ('active', 'chapter__cluster__country', 'established_date', 'date_added')
    search_fields = ('area_name', 'area_code', 'description', 'chapter__chapter_name')
    readonly_fields = ('area_id', 'date_added', 'date_updated')
    autocomplete_fields = ['chapter']
    
    fieldsets = (
        ('Area Information', {
            'fields': ('area_name', 'area_code', 'chapter', 'description', 'active', 'longitude', 'latitude')
        }),
        ('Identification', {
            'fields': ('area_id',),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('established_date', 'date_added', 'date_updated'),
            'classes': ('collapse',)
        }),
    )


@admin.register(RelativeArea)
class RelativeAreaAdmin(admin.ModelAdmin):
    list_display = ('name', 'relative_area')
    search_fields = ('name', 'relative_area__area_name')
    autocomplete_fields = ['relative_area']
    
    fieldsets = (
        ('Relative Location Information', {
            'fields': ('name', 'relative_area')
        }),
    )


class VenueMetadataInline(admin.TabularInline):
    model = VenueMetadata
    extra = 1
    readonly_fields = ('added_at', 'updated_at')


class VenueContactInline(admin.TabularInline):
    model = VenueContact
    extra = 1
    readonly_fields = ('added_at', 'updated_at')


class RoomVenueInline(admin.TabularInline):
    model = RoomVenue
    extra = 1
    readonly_fields = ('added_at', 'updated_at')


@admin.register(POI)
class POIAdmin(admin.ModelAdmin):
    list_display = ('name', 'poi_type', 'city', 'postcode', 'created_at', 'created_by')
    list_filter = ('poi_type', 'city', 'created_at')
    search_fields = ('name', 'description', 'address', 'city', 'postcode')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'poi_type', 'description')
        }),
        ('Location Details', {
            'fields': ('address', 'postcode', 'city', 'latitude', 'longitude')
        }),
        ('Metadata', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('get_venue_name', 'get_poi_type', 'capacity', 'added_by', 'added_at')
    list_filter = ('poi__poi_type', 'added_at')
    search_fields = ('poi__name', 'description', 'instructions')
    readonly_fields = ('added_at', 'updated_at')
    inlines = [VenueContactInline, RoomVenueInline, VenueMetadataInline]
    
    fieldsets = (
        ('Venue Information', {
            'fields': ('poi', 'description', 'instructions', 'notes', 'capacity')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_venue_name(self, obj):
        return obj.poi.name
    get_venue_name.short_description = 'Venue Name'
    
    def get_poi_type(self, obj):
        return obj.poi.poi_type
    get_poi_type.short_description = 'Type'


@admin.register(RoomVenue)
class RoomVenueAdmin(admin.ModelAdmin):
    list_display = ('room_name', 'get_venue_name', 'capacity', 'added_by', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('room_name', 'description', 'venue__poi__name')
    readonly_fields = ('added_at', 'updated_at')
    
    fieldsets = (
        ('Room Information', {
            'fields': ('venue', 'room_name', 'description', 'capacity')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_venue_name(self, obj):
        return obj.venue.poi.name
    get_venue_name.short_description = 'Venue'


@admin.register(VenueContact)
class VenueContactAdmin(admin.ModelAdmin):
    list_display = ('contact_name', 'get_venue_name', 'role', 'email', 'phone_number', 'added_at')
    list_filter = ('role', 'added_at')
    search_fields = ('contact_name', 'email', 'phone_number', 'venue__poi__name')
    readonly_fields = ('added_at', 'updated_at')
    
    fieldsets = (
        ('Contact Information', {
            'fields': ('venue', 'contact_name', 'phone_number', 'email', 'role')
        }),
        ('Metadata', {
            'fields': ('added_by', 'added_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_venue_name(self, obj):
        return obj.venue.poi.name
    get_venue_name.short_description = 'Venue'


@admin.register(VenueMetadata)
class VenueMetadataAdmin(admin.ModelAdmin):
    list_display = ('venue', 'added_by', 'added_at', 'updated_at')
    list_filter = ('added_at', 'updated_at')
    search_fields = ('venue__poi__name',)
    readonly_fields = ('added_at', 'updated_at')
