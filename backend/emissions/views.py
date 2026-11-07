from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mixins import OrganisationScopedMixin
from accounts.models import AuditLog
from accounts.permissions import CanEditDataOrReadOnly, IsOrganisationMember
from accounts.services import record_audit

from .calculations import EmissionsError
from .models import ActivityRecord, EmissionFactor
from .serializers import (
    ActivityFilterSerializer,
    ActivityRecordSerializer,
    CalculationSerializer,
    EmissionFactorSerializer,
)
from .services import import_activities, scope_totals, update_activity

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_REPORTED_ERRORS = 100


class EmissionFactorViewSet(
    OrganisationScopedMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Correct factors without silently changing saved activity calculations."""

    queryset = EmissionFactor.objects.all()
    serializer_class = EmissionFactorSerializer
    permission_classes = [CanEditDataOrReadOnly]

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def get_object(self):
        instance = super().get_object()
        if self.action in {"update", "partial_update", "recalculate"}:
            return get_object_or_404(self.get_queryset().select_for_update(), pk=instance.pk)
        return instance

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def recalculate(self, request, pk=None):
        factor = self.get_object()
        # Reject stale confirmation dialogs after another member corrects this factor.
        expected = EmissionFactorSerializer(factor).data
        if request.data.get("factor") != dict(expected):
            return Response(
                {"detail": "The factor changed. Refresh and confirm again."}, status=409
            )
        records = (
            ActivityRecord.objects.select_for_update()
            .filter(organisation=request.user.organisation, factor=factor)
            .order_by("pk")
        )
        updated = 0
        for record in records:
            before = dict(ActivityRecordSerializer(record).data)
            try:
                update_activity(record, factor=factor, refresh_factor=True)
            except EmissionsError as exc:
                raise serializers.ValidationError(
                    {"detail": f"Activity {record.pk}: {exc}"}
                ) from exc
            after = dict(ActivityRecordSerializer(record).data)
            if before != after:
                record_audit(
                    actor=request.user,
                    action=AuditLog.Action.UPDATE,
                    instance=record,
                    changes={"reason": "factor_recalculation", "before": before, "after": after},
                )
                updated += 1
        return Response({"updated": updated})


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
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
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

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    def get_object(self):
        if self.action in {"update", "partial_update", "destroy"}:
            # Lock only the activity row, avoiding locks on nullable related rows.
            instance = super().get_object()
            return get_object_or_404(ActivityRecord.objects.select_for_update(), pk=instance.pk)
        return super().get_object()

    def perform_update(self, serializer):
        before = dict(self.get_serializer(serializer.instance).data)
        instance = serializer.save()
        after = dict(self.get_serializer(instance).data)
        if before != after:
            record_audit(
                actor=self.request.user,
                action=AuditLog.Action.UPDATE,
                instance=instance,
                changes={"before": before, "after": after},
            )

    def perform_destroy(self, instance):
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.DELETE,
            instance=instance,
            changes={"before": dict(self.get_serializer(instance).data)},
        )
        instance.delete()

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
