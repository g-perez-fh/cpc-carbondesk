from decimal import Decimal

from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mixins import OrganisationScopedMixin
from accounts.permissions import CanEditDataOrReadOnly, IsOrganisationMember

from .models import ActivityRecord, EmissionFactor
from .serializers import (
    ActivityFilterSerializer,
    ActivityRecordSerializer,
    CalculationSerializer,
    EmissionFactorSerializer,
)
from .services import import_activities, scope_totals

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_REPORTED_ERRORS = 100


class EmissionFactorViewSet(
    OrganisationScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Factors are added as new versions; existing factors are not edited in this slice."""

    queryset = EmissionFactor.objects.all()
    serializer_class = EmissionFactorSerializer
    permission_classes = [CanEditDataOrReadOnly]

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)


class ActivityPagination(PageNumberPagination):
    page_size = 20


def filtered_activities(request):
    filters = ActivityFilterSerializer(data=request.query_params, context={"request": request})
    filters.is_valid(raise_exception=True)
    records = ActivityRecord.objects.filter(organisation=request.user.organisation)
    for name, lookup in {
        "start": "date__gte",
        "end": "date__lt",
        "scope": "scope",
        "site": "site",
    }.items():
        if name in filters.validated_data:
            records = records.filter(**{lookup: filters.validated_data[name]})
    return records


class ActivityRecordViewSet(
    OrganisationScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ActivityRecord.objects.all()
    serializer_class = ActivityRecordSerializer
    permission_classes = [CanEditDataOrReadOnly]
    pagination_class = ActivityPagination

    def get_queryset(self):
        return filtered_activities(self.request).select_related("site", "factor")

    def extra_save_kwargs(self):
        return {"created_by": self.request.user}

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)

    @action(detail=False, methods=["post"], url_path="import")
    def import_csv(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": ["Choose a CSV file to import."]}, status=400)
        if upload.size > MAX_IMPORT_BYTES:
            return Response({"file": ["The file is larger than 5 MB."]}, status=400)
        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response({"file": ["The file must be UTF-8 encoded."]}, status=400)

        created, errors = import_activities(
            organisation=request.user.organisation,
            created_by=request.user,
            text=text,
        )
        if errors:
            messages = [
                f"Row {error['row']}: {error['message']}" for error in errors[:MAX_REPORTED_ERRORS]
            ]
            if len(errors) > MAX_REPORTED_ERRORS:
                messages.append(
                    f"and {len(errors) - MAX_REPORTED_ERRORS} more errors. "
                    "Fix these first, then upload the file again."
                )
            return Response({"file": messages}, status=400)
        return Response({"created": created, "unit": "kg CO2e"}, status=201)


class CalculationView(APIView):
    permission_classes = [IsOrganisationMember]

    def post(self, request):
        serializer = CalculationSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response({"kg_co2e": str(serializer.validated_data["kg_co2e"]), "unit": "kg CO2e"})


class SummaryView(APIView):
    permission_classes = [IsOrganisationMember]

    def get(self, request):
        records = filtered_activities(request)
        totals = scope_totals(records)
        return Response(
            {
                "count": records.count(),
                "demo_count": records.filter(is_demo=True).count(),
                "total_kg_co2e": str(sum(totals.values(), Decimal("0.00"))),
                "by_scope": {scope: str(value) for scope, value in totals.items()},
                "unit": "kg CO2e",
            }
        )
