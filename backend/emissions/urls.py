from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    ActivityRecordViewSet,
    CalculationView,
    EmissionFactorViewSet,
    ImportHistoryView,
    SummaryView,
)

router = SimpleRouter()
router.register("factors", EmissionFactorViewSet)
router.register("activities", ActivityRecordViewSet)

urlpatterns = [
    path("preview/", CalculationView.as_view(), name="emissions-preview"),
    path("summary/", SummaryView.as_view(), name="emissions-summary"),
    path("imports/", ImportHistoryView.as_view(), name="emissions-import-history"),
    *router.urls,
]
