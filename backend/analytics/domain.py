"""Plain-Python OOP model of the Analytics subsystem (Homework 1).

These classes mirror the Analytics UML diagram. They hold no Django imports and
no database access, so they can be imported and exercised without a Django
project configured. DashboardService and KpiCalculator operate on the shared
shared.models.ActivityRecord - the same shape the Django model and
stream_processing use - instead of ad-hoc dicts, so an activity record means
the same thing everywhere in the project. ChartBuilder and ReportExporter format
already-aggregated rows (chart points, report columns), which are a different
thing from a raw activity record, so they keep taking plain dicts.
"""

from datetime import datetime
from decimal import Decimal

PALETTE_HEX_LENGTH = 7
MIN_SCORE = 0
MAX_SCORE = 100


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


class DashboardService:
    """Builds the dashboard summary and trend for one organisation."""

    def __init__(self, org_id, filters=None, cache=None):
        self.org_id = org_id
        self.filters = filters if filters is not None else {}
        self.cache = cache if cache is not None else {}
        self._records = []

    def setup(self, records):
        """Load the activity records this service will summarise. Clears the cache."""
        self._records = list(records)
        self.cache = {}
        return self

    @property
    def org_id(self):
        return self._org_id

    @org_id.setter
    def org_id(self, value):
        if not isinstance(value, int) or value <= 0:
            raise ValueError("org_id must be a positive integer")
        self._org_id = value

    @property
    def filters(self):
        return self._filters

    @filters.setter
    def filters(self, value):
        if not isinstance(value, dict):
            raise TypeError("filters must be a dict")
        self._filters = dict(value)

    @property
    def cache(self):
        return self._cache

    @cache.setter
    def cache(self, value):
        if not isinstance(value, dict):
            raise TypeError("cache must be a dict")
        self._cache = value

    def _matches_filters(self, record):
        scope = self.filters.get("scope")
        site = self.filters.get("site")
        if scope is not None and record.scope != scope:
            return False
        if site is not None and record.site != site:
            return False
        return True

    def _filtered(self):
        return [record for record in self._records if self._matches_filters(record)]

    def summary(self):
        """Total kg CO2e per scope, cached per distinct set of filters."""
        key = ("summary", tuple(sorted(self.filters.items())))
        if key in self.cache:
            return self.cache[key]
        totals = {}
        for record in self._filtered():
            totals[record.scope] = totals.get(record.scope, Decimal("0")) + _as_decimal(
                record.kg_co2e
            )
        self.cache[key] = totals
        return totals

    def trend(self):
        """Total kg CO2e per month (derived from each record's date), oldest first."""
        key = ("trend", tuple(sorted(self.filters.items())))
        if key in self.cache:
            return self.cache[key]
        totals = {}
        for record in self._filtered():
            month = record.date.strftime("%Y-%m")
            totals[month] = totals.get(month, Decimal("0")) + _as_decimal(record.kg_co2e)
        rows = [{"month": month, "kg_co2e": totals[month]} for month in sorted(totals)]
        self.cache[key] = rows
        return rows


class KpiCalculator:
    """Scores how an organisation's emissions perform against a baseline."""

    def __init__(self, period, baseline_kg, score=0):
        self.period = period
        self.baseline_kg = baseline_kg
        self.score = score
        self._records = []

    def setup(self, records):
        """Load the activity records this calculator will score."""
        self._records = list(records)
        return self

    @property
    def period(self):
        return self._period

    @period.setter
    def period(self, value):
        if not value:
            raise ValueError("period must be a non-empty label, e.g. '2026' or '2026-Q1'")
        self._period = value

    @property
    def baseline_kg(self):
        return self._baseline_kg

    @baseline_kg.setter
    def baseline_kg(self, value):
        baseline = _as_decimal(value)
        if baseline < 0:
            raise ValueError("baseline_kg must not be negative")
        self._baseline_kg = baseline

    @property
    def score(self):
        return self._score

    @score.setter
    def score(self, value):
        if not MIN_SCORE <= value <= MAX_SCORE:
            raise ValueError(f"score must be between {MIN_SCORE} and {MAX_SCORE}")
        self._score = value

    def total_kg(self):
        amounts = (_as_decimal(record.kg_co2e) for record in self._records)
        return sum(amounts, Decimal("0"))

    def recompute_score(self):
        """Score of 100 at or below baseline, falling as emissions exceed it."""
        total = self.total_kg()
        if self.baseline_kg == 0:
            self.score = MAX_SCORE if total == 0 else MIN_SCORE
            return self.score
        ratio = total / self.baseline_kg
        if ratio <= 1:
            self.score = MAX_SCORE
        else:
            self.score = max(MIN_SCORE, min(MAX_SCORE, round(float((1 - (ratio - 1)) * 100))))
        return self.score

    def top_sources(self, limit=5):
        """The highest-emitting categories, largest first."""
        totals = {}
        for record in self._records:
            amount = _as_decimal(record.kg_co2e)
            totals[record.category] = totals.get(record.category, Decimal("0")) + amount
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        return [{"category": category, "kg_co2e": total} for category, total in ranked[:limit]]


class ChartBuilder:
    """Turns aggregated rows into chart specifications for the frontend."""

    def __init__(self, palette, title, data=None):
        self.palette = palette
        self.title = title
        self.data = data if data is not None else []

    def setup(self, data):
        """Replace the rows this chart will render."""
        self.data = list(data)
        return self

    @property
    def palette(self):
        return self._palette

    @palette.setter
    def palette(self, value):
        colors = list(value)
        if not colors:
            raise ValueError("palette must have at least one color")
        for color in colors:
            is_hex = isinstance(color, str) and len(color) == PALETTE_HEX_LENGTH
            if not (is_hex and color.startswith("#")):
                raise ValueError(f"invalid hex color: {color!r}")
        self._palette = colors

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("title must be a non-empty string")
        self._title = value

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = list(value)

    def donut(self):
        """A donut-chart spec: one slice per row, colors cycling through the palette."""
        slices = [
            {
                "label": row["label"],
                "value": row["value"],
                "color": self.palette[index % len(self.palette)],
            }
            for index, row in enumerate(self.data)
        ]
        return {"type": "donut", "title": self.title, "slices": slices}

    def line(self):
        """A line-chart spec: one point per row, in the given order."""
        points = [{"x": row["label"], "y": row["value"]} for row in self.data]
        return {"type": "line", "title": self.title, "color": self.palette[0], "points": points}


class ReportExporter:
    """Exports a set of rows as CSV or PDF for a given user."""

    FORMATS = ("csv", "pdf")

    def __init__(self, format, created_at=None, user_id=None):
        self.format = format
        self.created_at = created_at if created_at is not None else datetime.now()
        self.user_id = user_id
        self._rows = []
        self._columns = []

    def setup(self, rows, columns):
        """Load the rows and column order this report will export."""
        self._rows = list(rows)
        self._columns = list(columns)
        return self

    @property
    def format(self):
        return self._format

    @format.setter
    def format(self, value):
        if value not in self.FORMATS:
            raise ValueError(f"format must be one of {self.FORMATS}")
        self._format = value

    @property
    def created_at(self):
        return self._created_at

    @created_at.setter
    def created_at(self, value):
        if not isinstance(value, datetime):
            raise TypeError("created_at must be a datetime")
        self._created_at = value

    @property
    def user_id(self):
        return self._user_id

    @user_id.setter
    def user_id(self, value):
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise ValueError("user_id must be a positive integer or None")
        self._user_id = value

    def to_csv(self):
        """The loaded rows as CSV text, columns in the configured order."""
        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(self._columns)
        for row in self._rows:
            writer.writerow([row.get(column, "") for column in self._columns])
        return buffer.getvalue()

    def to_pdf(self):
        """A minimal valid single-page PDF listing the title and row count.

        This is a placeholder: the README already notes full PDF reports are
        follow-up work. It uses no third-party library, matching the
        "plain Python" requirement for this homework.
        """
        lines = [f"CarbonDesk report ({len(self._rows)} rows)", self.created_at.isoformat()]
        text_stream = (
            "BT /F1 14 Tf 72 760 Td " + " Td ".join(f"({line}) Tj 0 -20" for line in lines) + " ET"
        )
        objects = [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
            "/MediaBox [0 0 612 792] /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(text_stream)} >>\nstream\n{text_stream}\nendstream",
        ]
        pdf = "%PDF-1.4\n"
        offsets = []
        for index, body in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf += f"{index} 0 obj\n{body}\nendobj\n"
        xref_offset = len(pdf)
        pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
        for offset in offsets:
            pdf += f"{offset:010d} 00000 n \n"
        size = len(objects) + 1
        pdf += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
        return pdf.encode("latin-1")
