"""Save activities and expose company totals to the other subsystems."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from accounts.models import AuditLog, Site
from accounts.services import record_audit

from .calculations import CO2eCalculator, EmissionsError
from .csv_import import CsvImporter
from .models import ActivityRecord, EmissionFactor


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
def import_activities(*, organisation, created_by, text):
    """Validate the whole file, then save every row or none of them."""
    sites_by_name = {}
    for site in Site.objects.filter(organisation=organisation):
        sites_by_name.setdefault(site.name.strip(), []).append(site)
    factors_by_name = {}
    for factor in EmissionFactor.objects.filter(organisation=organisation):
        factors_by_name.setdefault(factor.name.strip(), []).append(factor)

    activities, errors = CsvImporter(
        text, sites_by_name=sites_by_name, factors_by_name=factors_by_name
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
            date=activity.date,
        )
        record_audit(actor=created_by, action=AuditLog.Action.CREATE, instance=record)
    return len(activities), []


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
