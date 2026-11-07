from django.urls import path

from .views import DashboardView, ExportCsvView

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="analytics-dashboard"),
    path("export/csv/", ExportCsvView.as_view(), name="analytics-export-csv"),
]
