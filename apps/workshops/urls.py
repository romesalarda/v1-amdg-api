from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.workshops.api.viewsets import (
    WorkshopViewSet,
    WorkshopRegistrationViewSet,
    WorkshopInterestSubmissionViewSet,
    WorkshopStaffViewSet,
)

app_name = 'workshops'

router = DefaultRouter()
router.register(r'list', WorkshopViewSet, basename='workshop')
router.register(r'registrations', WorkshopRegistrationViewSet, basename='workshopregistration')
router.register(r'interest-submissions', WorkshopInterestSubmissionViewSet, basename='workshopinterestsubmission')
router.register(r'staff', WorkshopStaffViewSet, basename='workshopstaff')

urlpatterns = [
    path('', include(router.urls)),
]
