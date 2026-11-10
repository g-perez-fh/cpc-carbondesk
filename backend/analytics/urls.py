from django.urls import path

from .views import DashboardView, ExportCsvView, ExportPdfView

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="analytics-dashboard"),
    path("export/csv/", ExportCsvView.as_view(), name="analytics-export-csv"),
    path("export/pdf/", ExportPdfView.as_view(), name="analytics-export-pdf"),
]
