"""Save activities and expose company totals to the other subsystems."""

from decimal import Decimal
from uuid import uuid4

from django.core.files.storage import default_storage
from django.db import DatabaseError, transaction
from django.db.models import Sum

from accounts.models import AuditLog, Department, Site
from accounts.services import record_audit

from .calculations import CO2eCalculator, EmissionsError
from .csv_import import CsvImporter
from .models import ActivityRecord, EmissionFactor, ImportLog


@transaction.atomic
def create_activity(*, organisation, created_by, factor, site, quantity, unit, **fields):
    if factor.organisation_id != organisation.pk or site.organisation_id != organisation.pk:
        raise EmissionsError("The factor and site must belong to the activity's organisation.")
    result = CO2eCalculator(factor.kg_per_unit, factor.unit).calculate(quantity, unit)
    return ActivityRecord.objects.create(
        organisation=organisation,
        created_by=created_by,
        factor=factor,
        site=site,
        quantity=quantity,
        unit=factor.unit,
        category=factor.name,
        scope=factor.scope,
        factor_value=factor.kg_per_unit,
        factor_source=factor.source,
        factor_year=factor.year,
        is_demo=factor.is_demo,
        kg_co2e=result,
        **fields,
    )


@transaction.atomic
def update_activity(record, *, refresh_factor=False, **fields):
    """Keep saved inputs unless another factor or explicit recalculation is requested."""
    factor = fields.get("factor", record.factor)
    site = fields.get("site", record.site)
    if (
        factor.organisation_id != record.organisation_id
        or site.organisation_id != record.organisation_id
    ):
        raise EmissionsError("The factor and site must belong to the activity's organisation.")
    if refresh_factor or factor.pk != record.factor_id:
        record.category = factor.name
        record.scope = factor.scope
        record.factor_value = factor.kg_per_unit
        record.factor_source = factor.source
        record.factor_year = factor.year
        record.is_demo = factor.is_demo
        record.unit = factor.unit
    result = CO2eCalculator(record.factor_value, record.unit).calculate(
        fields.get("quantity", record.quantity), fields.get("unit", record.unit)
    )
    for name, value in fields.items():
        setattr(record, name, value)
    record.kg_co2e = result
    record.save()
    return record


@transaction.atomic
def recalculate_factor_records(*, organisation, factor, actor):
    """Recompute saved totals after a factor correction; return how many changed.

    Chosen rule (our decision, not a professor requirement): stored ``kg_co2e``
    keeps the factor values it was calculated with until an explicit
    recalculation runs — this function is that path. It touches only records
    of ``factor`` inside ``organisation``. Every changed record gets one
    UPDATE audit entry whose ``before`` snapshot preserves the
    pre-correction values, so old numbers stay reconstructable from the
    append-only ``AuditLog.changes`` JSON field instead of a new history
    table. Limitation of that choice: snapshots store serializer
    representations (displayed strings such as "40.00"), not raw database
    values, and reconstruction pairs a record with its single audit entry.
    """
    # Imported here, not at module level: serializers.py imports service
    # functions from this module, so a top-level import would be circular.
    from .serializers import ActivityRecordSerializer

    updated = 0
    records = (
        ActivityRecord.objects.select_for_update()
        .filter(organisation=organisation, factor=factor)
        .order_by("pk")
    )
    for record in records:
        before = dict(ActivityRecordSerializer(record).data)
        try:
            update_activity(record, factor=factor, refresh_factor=True)
        except EmissionsError as exc:
            raise EmissionsError(f"Activity {record.pk}: {exc}") from exc
        after = dict(ActivityRecordSerializer(record).data)
        if before != after:
            record_audit(
                actor=actor,
                action=AuditLog.Action.UPDATE,
                instance=record,
                changes={"reason": "factor_recalculation", "before": before, "after": after},
            )
            updated += 1
    return updated


@transaction.atomic
def import_activities(*, organisation, created_by, text):
    """Validate the whole file, then save every row or none of them."""
    sites_by_name = {}
    for site in Site.objects.filter(organisation=organisation):
        sites_by_name.setdefault(site.name.strip(), []).append(site)
    factors_by_name = {}
    for factor in EmissionFactor.objects.filter(organisation=organisation):
        factors_by_name.setdefault(factor.name.strip(), []).append(factor)

    activities, errors = CsvImporter(
        text,
        sites_by_name=sites_by_name,
        factors_by_name=factors_by_name,
        departments_by_name={
            d.name: d for d in Department.objects.filter(organisation=organisation)
        },
    ).parse()
    if errors:
        return 0, errors

    for activity in activities:
        record = create_activity(
            organisation=organisation,
            created_by=created_by,
            factor=activity.factor,
            site=activity.site,
            quantity=activity.quantity,
            unit=activity.unit,
            description=activity.description,
            department=activity.department,
            date=activity.date,
        )
        record_audit(actor=created_by, action=AuditLog.Action.CREATE, instance=record)
    return len(activities), []


def persist_import(*, organisation, created_by, original_name, uploaded_file, text):
    """Persist one import attempt; file storage is private and removed on rollback.

    Raises OSError when the upload cannot be stored, or DatabaseError when the
    activities cannot be saved. Both exceptions happen after the attempt is
    recorded in `ImportLog` and are re-raised to the caller.
    """
    log = ImportLog.objects.create(
        organisation=organisation,
        created_by=created_by,
        original_name=original_name[:255],
        outcome=ImportLog.Outcome.FAILED,
    )
    suffix = original_name.rsplit(".", 1)[-1] if "." in original_name else "csv"
    safe_suffix = suffix.lower() if suffix.isalnum() and len(suffix) <= 8 else "csv"
    path = f"private/emissions-imports/{organisation.pk}/{uuid4().hex}.{safe_suffix}"
    try:
        # Reset upload's cursor if the caller already read it to validate/decode.
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)
        saved_path = default_storage.save(path, uploaded_file)
    except OSError:
        log.error_messages = [
            "Upload storage failed: an internal error occurred while saving the file."
        ]
        log.save(update_fields=["error_messages"])
        raise

    try:
        with transaction.atomic():
            log.stored_file.name = saved_path
            created, errors = import_activities(
                organisation=organisation, created_by=created_by, text=text
            )
            # Count rejected rows, not error messages: one row can fail
            # several validations and must be counted only once.
            rejected_rows = len({error["row"] for error in errors})
            log.row_count = created + rejected_rows
            log.accepted_count = created
            log.created_count = created
            log.rejected_count = rejected_rows
            if errors:
                log.outcome = ImportLog.Outcome.REJECTED
                log.error_messages = [
                    f"Row {error['row']}: {error['message']}" for error in errors[:100]
                ]
            else:
                log.outcome = ImportLog.Outcome.SUCCESS
            log.save()
        return log, created, errors
    except DatabaseError:
        default_storage.delete(saved_path)
        try:
            log.refresh_from_db()
            log.stored_file = ""
            log.outcome = ImportLog.Outcome.FAILED
            # Do not record str(exc): database errors can expose internal
            # table and constraint details through the import history view.
            log.error_messages = [
                "Database save failed: an internal error occurred while saving activities."
            ]
            log.save(update_fields=["stored_file", "outcome", "error_messages"])
        except DatabaseError:
            # A broken connection or aborted transaction can fail the
            # cleanup itself; the original DatabaseError is re-raised
            # regardless, so the caller still sees the real failure.
            pass
        raise


def scope_totals(records):
    totals = {scope: Decimal("0.00") for scope in (1, 2, 3)}
    for row in records.values("scope").annotate(total=Sum("kg_co2e")):
        totals[row["scope"]] = row["total"].quantize(Decimal("0.01"))
    return totals


def totals_by_scope(organisation, start, end):
    """Return kg CO2e per scope for start <= date < end, for one company only."""
    records = ActivityRecord.objects.filter(
        organisation=organisation, date__gte=start, date__lt=end
    )
    return scope_totals(records)
