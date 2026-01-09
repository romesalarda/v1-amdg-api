from django_filters import rest_framework as filters
from apps.users.models import Profile


class ProfileFilterSet(filters.FilterSet):
    """Advanced filtering for Profile model."""
    preferred_name = filters.CharFilter(lookup_expr='icontains')
    contact_phone = filters.CharFilter(lookup_expr='icontains')
    timezone = filters.CharFilter(lookup_expr='iexact')
    preferred_language = filters.ChoiceFilter(choices=[('en', 'English'), ('es', 'Spanish'), ('fr', 'French')])
    has_profile_picture = filters.BooleanFilter(method='filter_has_profile_picture')
    area_from = filters.NumberFilter(field_name='area_from__id')
    
    class Meta:
        model = Profile
        fields = ['preferred_name', 'contact_phone', 'timezone', 'preferred_language', 'area_from']
    
    def filter_has_profile_picture(self, queryset, name, value):
        if value:
            return queryset.exclude(profile_picture='')
        return queryset.filter(profile_picture='')
