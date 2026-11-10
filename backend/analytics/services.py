"""Read-only analytics over the emissions subsystem's activity records.

Every function receives a queryset that is already limited to one organisation, so
the dashboard can never mix companies. Nothing here writes to the database.
"""

import csv
import io
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from accounts.models import ReductionTarget
from accounts.services import target_progress
from emissions.models import ActivityRecord
from emissions.services import scope_totals

from .exceptions import ExportError, NoDataError

CENTS = Decimal("0.01")
TOP_SOURCES = 5
SCORE_MIN = Decimal("0")
SCORE_MAX = Decimal("100")
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


def filter_records(organisation, *, start=None, end=None, scope=None, site=None, department=None):
    """Activity records of one organisation, narrowed by optional filters (end is exclusive).

    ``department`` is either a ``Department`` belonging to this organisation, the literal
    string ``"unassigned"`` for records with no department, or ``None`` for no filter.
    """
    records = ActivityRecord.objects.filter(organisation=organisation)
    if start:
        records = records.filter(date__gte=start)
    if end:
        records = records.filter(date__lt=end)
    if scope:
        records = records.filter(scope=scope)
    if site:
        records = records.filter(site=site)
    if department == "unassigned":
        records = records.filter(department__isnull=True)
    elif department:
        records = records.filter(department=department)
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


def totals_by_department(records):
    """Total kg CO2e per department, largest first. Records without one are "Unassigned"."""
    rows = (
        records.values("department__name")
        .annotate(total=Sum("kg_co2e"))
        .order_by("-total", "department__name")
    )
    return [
        {"department": row["department__name"] or "Unassigned", "kg_co2e": _kg(row["total"])}
        for row in rows
    ]


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


def sustainability_score(organisation, as_of=None):
    """A 0-100 score of progress toward the organisation's "all scopes" reduction target.

    Compares today's annualised emissions to the straight-line pace between the target's
    baseline and target years, reusing the same expected/projected figures
    ``accounts.services.target_progress`` computes for the Targets card:

        score = 100 x (baseline - projected) / (baseline - expected)

    100 means on or ahead of the pace needed to hit the target, 0 means no progress has
    been made yet, and the result is clamped to 0-100 so overshooting the target or
    falling further behind never leaves that range (mirrors the validated 0-100
    ``KpiCalculator.score`` from the subsystem's earlier UML). Returns ``None`` when the
    organisation has not set an "all scopes" target - there is nothing to score against.
    """
    as_of = as_of or date.today()
    candidates = ReductionTarget.objects.filter(
        organisation=organisation, scope=ReductionTarget.Scope.ALL
    )
    target = candidates.filter(target_year__gte=as_of.year).order_by("target_year").first()
    target = target or candidates.order_by("-target_year").first()
    if target is None:
        return None

    progress = target_progress(target, as_of)
    baseline = Decimal(target.baseline_kg_co2e)
    expected_reduction = baseline - progress.expected_kg_co2e
    if expected_reduction <= 0:
        score = SCORE_MAX if progress.projected_kg_co2e <= progress.expected_kg_co2e else SCORE_MIN
    else:
        achieved_reduction = baseline - progress.projected_kg_co2e
        score = achieved_reduction / expected_reduction * 100
    return max(SCORE_MIN, min(SCORE_MAX, score)).quantize(Decimal("1"))


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
        "by_department": totals_by_department(records),
        "top_sources": top_sources(records),
        "targets": targets_overview(organisation),
        "sustainability_score": sustainability_score(organisation),
        "unit": "kg CO2e",
    }


def export_csv(records):
    """The filtered activity records as CSV text, one row per record."""
    if not records.exists():
        raise NoDataError()
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


def _filter_period_label(query_params):
    """Human-readable period from raw ?start=&end= query params (already validated)."""
    start, end = query_params.get("start"), query_params.get("end")
    if not start and not end:
        return "All dates"
    return f"{start or 'the beginning'} to {end or 'today'} (end exclusive)"


def _pdf_table(story, styles, title, headers, rows):
    section = [Paragraph(title, styles["Heading3"])]
    if not rows:
        section.append(Paragraph("No data.", styles["Normal"]))
    else:
        table = Table([headers, *rows], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        section.append(table)
    story.append(KeepTogether(section))
    story.append(Spacer(1, 0.4 * cm))


def _build_pdf(organisation, records, query_params, user):
    by_scope = scope_totals(records)
    total = sum(by_scope.values(), Decimal("0.00"))
    styles = getSampleStyleSheet()
    story = [
        Paragraph(organisation.name, styles["Title"]),
        Paragraph("Emissions report", styles["Heading2"]),
        Paragraph(f"Period: {_filter_period_label(query_params)}", styles["Normal"]),
        Paragraph(
            f"Generated: {date.today().isoformat()} by {user.get_username()}", styles["Normal"]
        ),
        Spacer(1, 0.5 * cm),
    ]
    _pdf_table(
        story,
        styles,
        "KPI summary",
        ["Metric", "Value"],
        [
            ["Total emissions", f"{total:,.2f} kg CO2e"],
            ["Total emissions", f"{(total / Decimal('1000')):,.3f} t CO2e"],
            ["Activity records", str(records.count())],
            ["Sites reporting", str(records.values("site").distinct().count())],
        ],
    )
    _pdf_table(
        story,
        styles,
        "Totals by scope",
        ["Scope", "kg CO2e"],
        [[f"Scope {scope}", f"{amount:,.2f}"] for scope, amount in sorted(by_scope.items())],
    )
    _pdf_table(
        story,
        styles,
        "Totals by site",
        ["Site", "kg CO2e"],
        [[row["site"], f"{row['kg_co2e']:,.2f}"] for row in totals_by_site(records)],
    )
    _pdf_table(
        story,
        styles,
        "Totals by department",
        ["Department", "kg CO2e"],
        [[row["department"], f"{row['kg_co2e']:,.2f}"] for row in totals_by_department(records)],
    )
    _pdf_table(
        story,
        styles,
        "Top 5 sources",
        ["Category", "Scope", "kg CO2e", "Share"],
        [
            [
                row["category"],
                f"Scope {row['scope']}",
                f"{row['kg_co2e']:,.2f}",
                f"{row['share_percent']}%",
            ]
            for row in top_sources(records)
        ],
    )
    _pdf_table(
        story,
        styles,
        "Target progress",
        ["Target", "Status", "Projected", "Target"],
        [
            [
                row["label"],
                row["status"].replace("_", " "),
                f"{row['projected_kg_co2e']} kg CO2e",
                f"{row['target_kg_co2e']} kg CO2e",
            ]
            for row in targets_overview(organisation)
        ],
    )

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, title="CarbonDesk emissions report").build(story)
    return buffer.getvalue()


def export_pdf(organisation, records, query_params, user):
    """A PDF summary of the dashboard for these filtered records, as raw PDF bytes."""
    if not records.exists():
        raise NoDataError()
    try:
        return _build_pdf(organisation, records, query_params, user)
    except NoDataError:
        raise
    except Exception as exc:
        raise ExportError(f"The PDF report could not be generated: {exc}") from exc
