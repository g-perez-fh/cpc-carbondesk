from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ActivityRecordViewSet, CalculationView, EmissionFactorViewSet, SummaryView

router = SimpleRouter()
router.register("factors", EmissionFactorViewSet)
router.register("activities", ActivityRecordViewSet)

urlpatterns = [
    path("preview/", CalculationView.as_view(), name="emissions-preview"),
    path("summary/", SummaryView.as_view(), name="emissions-summary"),
    *router.urls,
]
