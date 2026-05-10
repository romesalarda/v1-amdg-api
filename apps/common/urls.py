from django.urls import path
from apps.common.api.views import TimezoneListView

urlpatterns = [
    path('timezones/', TimezoneListView.as_view(), name='timezone-list'),
]
