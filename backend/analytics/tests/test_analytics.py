import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from accounts.models import Organisation, ReductionTarget, Site
from analytics import services
from emissions.models import ActivityRecord, EmissionFactor

pytestmark = pytest.mark.django_db


@pytest.fixture
def sites(organisation):
    return {
        "office": Site.objects.create(organisation=organisation, name="Main office"),
        "plant": Site.objects.create(organisation=organisation, name="Plant"),
    }


@pytest.fixture
def factors(organisation):
    def factor(name, scope, unit):
        return EmissionFactor.objects.create(
            organisation=organisation,
            name=name,
            scope=scope,
            unit=unit,
            kg_per_unit=Decimal("1"),
            source="Synthetic test factor",
            year=2026,
        )

    return {
        "diesel": factor("Diesel", 1, "l"),
        "power": factor("Electricity", 2, "kWh"),
        "flights": factor("Flights", 3, "km"),
    }


def add(organisation, site, factor, day, kg):
    return ActivityRecord.objects.create(
        organisation=organisation,
        site=site,
        factor=factor,
        description=f"{factor.name} {day}",
        date=day,
        quantity=Decimal(kg),
        category=factor.name,
        scope=factor.scope,
        unit=factor.unit,
        factor_value=factor.kg_per_unit,
        factor_source=factor.source,
        factor_year=factor.year,
        kg_co2e=Decimal(kg),
    )


@pytest.fixture
def records(organisation, sites, factors):
    add(organisation, sites["office"], factors["power"], date(2026, 1, 10), "100")
    add(organisation, sites["office"], factors["power"], date(2026, 2, 10), "150")
    add(organisation, sites["plant"], factors["diesel"], date(2026, 2, 20), "400")
    add(organisation, sites["plant"], factors["flights"], date(2026, 3, 5), "50.5")
    return ActivityRecord.objects.filter(organisation=organisation)


def test_monthly_trend_groups_by_month(records):
    assert services.monthly_trend(records) == [
        {"month": "2026-01", "kg_co2e": Decimal("100.00")},
        {"month": "2026-02", "kg_co2e": Decimal("550.00")},
        {"month": "2026-03", "kg_co2e": Decimal("50.50")},
    ]


def test_totals_by_site_largest_first(records):
    assert services.totals_by_site(records) == [
        {"site": "Plant", "kg_co2e": Decimal("450.50")},
        {"site": "Main office", "kg_co2e": Decimal("250.00")},
    ]


def test_top_sources_have_shares(records):
    top = services.top_sources(records, limit=2)
    assert [row["category"] for row in top] == ["Diesel", "Electricity"]
    assert top[0]["share_percent"] == Decimal("57.10")
    assert top[1]["records"] == 2


def test_dashboard_kpis(organisation, records):
    data = services.dashboard(organisation, records)
    assert data["total_kg_co2e"] == Decimal("700.50")
    assert data["record_count"] == 4
    assert data["site_count"] == 2
    assert data["largest_scope"] == 1
    assert data["by_scope"] == {1: Decimal("400.00"), 2: Decimal("250.00"), 3: Decimal("50.50")}


def test_dashboard_without_data(organisation):
    data = services.dashboard(organisation, ActivityRecord.objects.none())
    assert data["total_kg_co2e"] == Decimal("0.00")
    assert data["largest_scope"] is None
    assert data["trend"] == [] and data["top_sources"] == []


def test_filters_narrow_records(organisation, sites, records):
    assert services.filter_records(organisation, scope=2).count() == 2
    assert services.filter_records(organisation, site=sites["plant"]).count() == 2
    february = services.filter_records(organisation, start=date(2026, 2, 1), end=date(2026, 3, 1))
    assert february.count() == 2


def test_dashboard_api(api_for, viewer_user, records):
    response = api_for(viewer_user).get("/api/analytics/dashboard/", {"scope": 2})
    assert response.status_code == 200
    assert response.data["total_kg_co2e"] == "250.00"
    assert response.json()["by_scope"]["2"] == "250.00"
    assert response.data["trend"][0] == {"month": "2026-01", "kg_co2e": "100.00"}


def test_dashboard_api_rejects_bad_dates(api_for, viewer_user):
    response = api_for(viewer_user).get(
        "/api/analytics/dashboard/", {"start": "2026-03-01", "end": "2026-02-01"}
    )
    assert response.status_code == 400


def test_dashboard_requires_login(client):
    assert client.get("/api/analytics/dashboard/").status_code in {401, 403}


def test_other_companies_are_never_included(api_for, viewer_user, records, factors):
    other = Organisation.objects.create(name="Other AG")
    other_site = Site.objects.create(organisation=other, name="Elsewhere")
    add(other, other_site, factors["power"], date(2026, 1, 1), "9999")
    response = api_for(viewer_user).get("/api/analytics/dashboard/")
    assert response.data["total_kg_co2e"] == "700.50"
    assert "Elsewhere" not in [row["site"] for row in response.data["by_site"]]


def test_site_filter_from_another_company_is_rejected(api_for, viewer_user):
    other = Organisation.objects.create(name="Other AG")
    other_site = Site.objects.create(organisation=other, name="Elsewhere")
    response = api_for(viewer_user).get("/api/analytics/dashboard/", {"site": other_site.pk})
    assert response.status_code == 400


def test_dashboard_includes_target_progress(api_for, viewer_user, organisation, records):
    ReductionTarget.objects.create(
        organisation=organisation,
        scope=ReductionTarget.Scope.ALL,
        baseline_year=2024,
        baseline_kg_co2e=Decimal("10000"),
        target_year=2030,
        reduction_percent=Decimal("40"),
    )
    targets = api_for(viewer_user).get("/api/analytics/dashboard/").data["targets"]
    assert len(targets) == 1
    assert targets[0]["target_kg_co2e"] == "6000.00"
    assert targets[0]["status"] in {"on_track", "at_risk", "off_track", "no_data"}


def test_csv_export(api_for, viewer_user, records):
    response = api_for(viewer_user).get("/api/analytics/export/csv/", {"scope": 2})
    assert response.status_code == 200
    assert response.data["rows"] == 2
    rows = list(csv.DictReader(io.StringIO(response.data["content"])))
    assert [row["kg_co2e"] for row in rows] == ["100.00", "150.00"]
    assert rows[0]["site"] == "Main office"
    assert response.data["filename"].endswith(".csv")
