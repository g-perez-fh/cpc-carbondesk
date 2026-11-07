"""Read-only analytics over the emissions subsystem's activity records.

Every function receives a queryset that is already limited to one organisation, so
the dashboard can never mix companies. Nothing here writes to the database.
"""

import csv
import io
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth

from accounts.models import ReductionTarget
from accounts.services import target_progress
from emissions.models import ActivityRecord
from emissions.services import scope_totals

CENTS = Decimal("0.01")
TOP_SOURCES = 5
CSV_COLUMNS = [
    "date",
    "description",
    "site",
    "category",
    "scope",
    "quantity",
    "unit",
    "factor_value",
    "factor_source",
    "factor_year",
    "kg_co2e",
]


def filter_records(organisation, *, start=None, end=None, scope=None, site=None):
    """Activity records of one organisation, narrowed by optional filters (end is exclusive)."""
    records = ActivityRecord.objects.filter(organisation=organisation)
    if start:
        records = records.filter(date__gte=start)
    if end:
        records = records.filter(date__lt=end)
    if scope:
        records = records.filter(scope=scope)
    if site:
        records = records.filter(site=site)
    return records


def _kg(value):
    return (value or Decimal("0")).quantize(CENTS)


def monthly_trend(records):
    """Total kg CO2e per calendar month, oldest first."""
    rows = (
        records.annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("kg_co2e"))
        .order_by("month")
    )
    return [{"month": row["month"].strftime("%Y-%m"), "kg_co2e": _kg(row["total"])} for row in rows]


def totals_by_site(records):
    """Total kg CO2e per site, largest first."""
    rows = (
        records.values("site__name").annotate(total=Sum("kg_co2e")).order_by("-total", "site__name")
    )
    return [{"site": row["site__name"], "kg_co2e": _kg(row["total"])} for row in rows]


def top_sources(records, limit=TOP_SOURCES):
    """The emission categories with the highest totals, with their share of the total."""
    grand_total = records.aggregate(total=Sum("kg_co2e"))["total"] or Decimal("0")

    def share(total):
        return _kg(total / grand_total * 100) if grand_total else Decimal("0.00")

    rows = (
        records.values("category", "scope")
        .annotate(total=Sum("kg_co2e"), count=Count("id"))
        .order_by("-total", "category")[:limit]
    )
    return [
        {
            "category": row["category"],
            "scope": row["scope"],
            "records": row["count"],
            "kg_co2e": _kg(row["total"]),
            "share_percent": share(row["total"]),
        }
        for row in rows
    ]


def targets_overview(organisation):
    """Progress for each reduction target, reusing the accounts subsystem's calculation."""
    overview = []
    for target in ReductionTarget.objects.filter(organisation=organisation):
        progress = target_progress(target)
        overview.append(
            {
                "id": target.pk,
                "scope": target.scope,
                "label": str(target),
                "target_year": target.target_year,
                **progress.as_dict(),
            }
        )
    return overview


def dashboard(organisation, records):
    """Everything the dashboard page shows, in one response."""
    by_scope = scope_totals(records)
    total = sum(by_scope.values(), Decimal("0.00"))
    largest_scope = max(by_scope, key=by_scope.get) if total else None
    return {
        "total_kg_co2e": total,
        "record_count": records.count(),
        "site_count": records.values("site").distinct().count(),
        "largest_scope": largest_scope,
        "by_scope": by_scope,
        "trend": monthly_trend(records),
        "by_site": totals_by_site(records),
        "top_sources": top_sources(records),
        "targets": targets_overview(organisation),
        "unit": "kg CO2e",
    }


def export_csv(records):
    """The filtered activity records as CSV text, one row per record."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for record in records.select_related("site").order_by("date", "id"):
        writer.writerow(
            [
                record.date.isoformat(),
                record.description,
                record.site.name,
                record.category,
                record.scope,
                record.quantity,
                record.unit,
                record.factor_value,
                record.factor_source,
                record.factor_year,
                record.kg_co2e,
            ]
        )
    return buffer.getvalue()
