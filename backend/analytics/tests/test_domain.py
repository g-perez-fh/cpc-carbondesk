"""Plain-Python tests for the Homework 1 OOP classes. No Django, no database."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from analytics.domain import ChartBuilder, DashboardService, KpiCalculator, ReportExporter
from shared.models import ActivityRecord


def make_record(scope, site, record_date, category, kg_co2e):
    return ActivityRecord(
        organisation_id=1,
        site=site,
        date=record_date,
        scope=scope,
        category=category,
        quantity=Decimal("1"),
        unit="unit",
        factor_value=Decimal("1"),
        kg_co2e=Decimal(str(kg_co2e)),
    )


RECORDS = [
    make_record(1, "Plant", date(2026, 1, 10), "Diesel", 100),
    make_record(2, "Office", date(2026, 1, 20), "Electricity", 50),
    make_record(2, "Office", date(2026, 2, 5), "Electricity", 75),
]


def test_dashboard_service_validates_org_id():
    with pytest.raises(ValueError):
        DashboardService(org_id=0)


def test_dashboard_service_summary_groups_by_scope():
    service = DashboardService(org_id=1).setup(RECORDS)
    assert service.summary() == {1: Decimal("100"), 2: Decimal("125")}


def test_dashboard_service_filters_by_scope():
    service = DashboardService(org_id=1, filters={"scope": 2}).setup(RECORDS)
    assert service.summary() == {2: Decimal("125")}


def test_dashboard_service_trend_is_sorted_by_month():
    service = DashboardService(org_id=1).setup(RECORDS)
    assert service.trend() == [
        {"month": "2026-01", "kg_co2e": Decimal("150")},
        {"month": "2026-02", "kg_co2e": Decimal("75")},
    ]


def test_dashboard_service_caches_summary():
    service = DashboardService(org_id=1).setup(RECORDS)
    first = service.summary()
    service._records.append(make_record(1, "Plant", date(2026, 3, 1), "Diesel", 999))
    assert service.summary() is first


def test_kpi_calculator_rejects_negative_baseline():
    with pytest.raises(ValueError):
        KpiCalculator(period="2026", baseline_kg=-1)


def test_kpi_calculator_rejects_out_of_range_score():
    calc = KpiCalculator(period="2026", baseline_kg=100)
    with pytest.raises(ValueError):
        calc.score = 101


def test_kpi_calculator_top_sources_largest_first():
    calc = KpiCalculator(period="2026", baseline_kg=100).setup(RECORDS)
    top = calc.top_sources(limit=1)
    assert top == [{"category": "Electricity", "kg_co2e": Decimal("125")}]


def test_kpi_calculator_recompute_score_at_or_under_baseline():
    calc = KpiCalculator(period="2026", baseline_kg=1000).setup(RECORDS)
    assert calc.recompute_score() == 100


def test_kpi_calculator_recompute_score_over_baseline():
    calc = KpiCalculator(period="2026", baseline_kg=100).setup(RECORDS)
    assert calc.recompute_score() < 100


def test_chart_builder_validates_palette():
    with pytest.raises(ValueError):
        ChartBuilder(palette=["notacolor"], title="Scopes")


def test_chart_builder_rejects_empty_title():
    with pytest.raises(ValueError):
        ChartBuilder(palette=["#112233"], title="   ")


def test_chart_builder_donut_cycles_palette():
    builder = ChartBuilder(palette=["#111111", "#222222"], title="By scope")
    builder.setup(
        [
            {"label": "Scope 1", "value": 10},
            {"label": "Scope 2", "value": 20},
            {"label": "Scope 3", "value": 5},
        ]
    )
    donut = builder.donut()
    assert donut["type"] == "donut"
    assert [s["color"] for s in donut["slices"]] == ["#111111", "#222222", "#111111"]


def test_chart_builder_line_has_ordered_points():
    builder = ChartBuilder(palette=["#111111"], title="Trend")
    builder.setup([{"label": "Jan", "value": 10}, {"label": "Feb", "value": 20}])
    line = builder.line()
    assert line["points"] == [{"x": "Jan", "y": 10}, {"x": "Feb", "y": 20}]


def test_report_exporter_rejects_bad_format():
    with pytest.raises(ValueError):
        ReportExporter(format="xml")


def test_report_exporter_rejects_bad_user_id():
    with pytest.raises(ValueError):
        ReportExporter(format="csv", user_id=0)


def test_report_exporter_to_csv():
    exporter = ReportExporter(format="csv", created_at=datetime(2026, 1, 1), user_id=1)
    exporter.setup([{"site": "Plant", "kg_co2e": "100"}], ["site", "kg_co2e"])
    csv_text = exporter.to_csv()
    assert csv_text.splitlines() == ["site,kg_co2e", "Plant,100"]


def test_report_exporter_to_pdf_is_a_valid_pdf_byte_string():
    exporter = ReportExporter(format="pdf", created_at=datetime(2026, 1, 1), user_id=1)
    exporter.setup([{"site": "Plant", "kg_co2e": "100"}], ["site", "kg_co2e"])
    pdf_bytes = exporter.to_pdf()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert pdf_bytes.endswith(b"%%EOF")
