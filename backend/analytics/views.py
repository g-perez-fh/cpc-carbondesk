"""Read-only analytics endpoints. Every member of an organisation may view them."""

import base64
from datetime import date
from decimal import Decimal

from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Department
from accounts.permissions import IsOrganisationMember
from emissions.serializers import ActivityFilterSerializer

from . import services
from .exceptions import AnalyticsError, InvalidFilterError


class AnalyticsAPIView(APIView):
    """An APIView that turns any AnalyticsError into a clean JSON error response."""

    def handle_exception(self, exc):
        if isinstance(exc, AnalyticsError):
            return Response(exc.as_response_data(), status=exc.status_code)
        return super().handle_exception(exc)


def as_json(value):
    """Send money-like Decimals as strings, the same way the other subsystems do."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: as_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_json(item) for item in value]
    return value


def _resolve_department(organisation, raw):
    """Turn a raw ?department= value into a Department, "unassigned", or None.

    Kept out of ActivityFilterSerializer so the emissions subsystem's serializer stays
    untouched; this is analytics' own second line of defense on top of this check.
    """
    if not raw:
        return None
    if raw == "unassigned":
        return "unassigned"
    if not raw.isdigit():
        raise InvalidFilterError("This department does not belong to your organisation.")
    try:
        return Department.objects.get(pk=int(raw), organisation=organisation)
    except Department.DoesNotExist:
        raise InvalidFilterError("This department does not belong to your organisation.") from None


def filtered_records(request):
    """Validate ?start=&end=&scope=&site=&department= and return the matching records."""
    filters = ActivityFilterSerializer(data=request.query_params, context={"request": request})
    filters.is_valid(raise_exception=True)
    department = _resolve_department(
        request.user.organisation, request.query_params.get("department")
    )
    return services.filter_records(
        request.user.organisation, department=department, **filters.validated_data
    )


class DashboardView(AnalyticsAPIView):
    permission_classes = [IsOrganisationMember]

    def get(self, request):
        records = filtered_records(request)
        return Response(as_json(services.dashboard(request.user.organisation, records)))


class ExportCsvView(AnalyticsAPIView):
    """Return the CSV inside JSON so the frontend can reuse its normal API helper."""

    permission_classes = [IsOrganisationMember]

    def get(self, request):
        records = filtered_records(request)
        return Response(
            {
                "filename": f"carbondesk-emissions-{date.today().isoformat()}.csv",
                "rows": records.count(),
                "content": services.export_csv(records),
            }
        )


class ExportPdfView(AnalyticsAPIView):
    """Return the PDF base64-encoded inside JSON, the same way the CSV export does."""

    permission_classes = [IsOrganisationMember]

    def get(self, request):
        records = filtered_records(request)
        content = services.export_pdf(
            request.user.organisation, records, request.query_params, request.user
        )
        return Response(
            {
                "filename": f"carbondesk-emissions-{date.today().isoformat()}.pdf",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
