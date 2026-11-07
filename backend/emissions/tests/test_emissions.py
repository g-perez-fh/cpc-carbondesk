from datetime import date, timedelta
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import AuditLog, Organisation, Site, User
from assistant.context import build_snapshot
from core import emissions_data
from emissions.calculations import CO2eCalculator, EmissionsError
from emissions.models import ActivityRecord, EmissionFactor
from emissions.services import totals_by_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def factor(organisation):
    return EmissionFactor.objects.create(
        organisation=organisation,
        name="Demo electricity",
        scope=2,
        unit="kWh",
        kg_per_unit=Decimal("0.4"),
        source="Synthetic test factor",
        year=2026,
        is_demo=True,
    )


@pytest.fixture
def site(organisation):
    return Site.objects.create(organisation=organisation, name="Main office")


def payload(factor_obj, site_obj, **changes):
    data = {
        "description": "Office electricity",
        "date": "2026-01-15",
        "factor": factor_obj.pk,
        "site": site_obj.pk,
        "quantity": "100",
        "unit": "kWh",
    }
    return data | changes


def test_create_record_calculates_and_audits(api_for, admin_user, factor, site):
    response = api_for(admin_user).post(
        "/api/emissions/activities/", payload(factor, site, kg_co2e="999", scope=1), format="json"
    )
    assert response.status_code == 201, response.data
    body = response.json()
    assert body["kg_co2e"] == "40.00"
    assert body["scope"] == 2
    assert body["factor_source"] == "Synthetic test factor"
    assert body["is_demo"] is True
    record = ActivityRecord.objects.get(pk=body["id"])
    assert record.organisation == admin_user.organisation
    assert record.created_by == admin_user
    assert AuditLog.objects.filter(object_id=str(record.pk), action="create").exists()


def test_preview_matches_saved_calculation(api_for, admin_user, factor, site):
    client = api_for(admin_user)
    data = payload(factor, site, quantity="2.5125")
    preview = client.post("/api/emissions/preview/", data, format="json")
    assert preview.status_code == 200
    assert preview.json()["kg_co2e"] == "1.01"
    assert ActivityRecord.objects.count() == 0
    saved = client.post("/api/emissions/activities/", data, format="json")
    assert saved.json()["kg_co2e"] == preview.json()["kg_co2e"]


@pytest.mark.parametrize(
    "changes, field",
    [
        ({"quantity": "-1"}, "quantity"),
        ({"quantity": "NaN"}, "quantity"),
        ({"quantity": "Infinity"}, "quantity"),
        ({"quantity": "0.00001"}, "quantity"),
        ({"quantity": "10000000000"}, "quantity"),
        ({"quantity": ""}, "quantity"),
        ({"unit": "litres"}, "unit"),
        ({"date": "invalid"}, "date"),
        ({"date": str(date.today() + timedelta(days=1))}, "date"),
        ({"description": " "}, "description"),
        ({"site": None}, "site"),
        ({"factor": 999999}, "factor"),
    ],
)
def test_invalid_activity_does_not_write(api_for, admin_user, factor, site, changes, field):
    response = api_for(admin_user).post(
        "/api/emissions/activities/", payload(factor, site, **changes), format="json"
    )
    assert response.status_code == 400
    assert field in response.json()
    assert not ActivityRecord.objects.exists()
    assert not AuditLog.objects.exists()


def test_zero_quantity_is_valid(api_for, admin_user, factor, site):
    response = api_for(admin_user).post(
        "/api/emissions/activities/", payload(factor, site, quantity="0"), format="json"
    )
    assert response.status_code == 201
    assert response.json()["kg_co2e"] == "0.00"


def test_role_permissions(api_for, admin_user, viewer_user, make_member, factor, site):
    editor = make_member("editor", User.Role.EDITOR)
    data = payload(factor, site)
    assert APIClient().get("/api/emissions/activities/").status_code == 401
    assert api_for(viewer_user).post("/api/emissions/activities/", data).status_code == 403
    assert api_for(editor).post("/api/emissions/activities/", data).status_code == 201
    assert api_for(viewer_user).get("/api/emissions/activities/").json()["count"] == 1
    assert api_for(viewer_user).get("/api/emissions/summary/").status_code == 200
    user = User.objects.create_user(username="no-org")
    assert api_for(user).get("/api/emissions/activities/").status_code == 403


def test_other_company_references_rejected(api_for, admin_user, factor, site):
    other = Organisation.objects.create(name="Other")
    foreign_site = Site.objects.create(organisation=other, name="Other site")
    foreign_factor = EmissionFactor.objects.create(
        organisation=other,
        name="Private",
        scope=1,
        unit="litres",
        kg_per_unit=2,
        source="Example",
        year=2026,
    )
    client = api_for(admin_user)
    for changes, field in [
        ({"site": foreign_site.pk}, "site"),
        ({"factor": foreign_factor.pk}, "factor"),
    ]:
        response = client.post("/api/emissions/activities/", payload(factor, site, **changes))
        assert response.status_code == 400
        assert field in response.json()
    assert (
        client.post(
            "/api/emissions/preview/",
            {"factor": foreign_factor.pk, "quantity": 1, "unit": "litres"},
        ).status_code
        == 400
    )
    assert client.get(f"/api/emissions/factors/{foreign_factor.pk}/").status_code == 404
    assert len(client.get("/api/emissions/factors/").json()) == 1
    assert client.get("/api/emissions/summary/", {"site": foreign_site.pk}).status_code == 400


def test_records_and_totals_are_isolated(api_for, admin_user, make_member, factor, site):
    client = api_for(admin_user)
    record = client.post("/api/emissions/activities/", payload(factor, site)).json()
    other = Organisation.objects.create(name="Other")
    outsider = make_member("outsider", org=other)
    outsider_client = api_for(outsider)
    assert outsider_client.get("/api/emissions/activities/").json()["count"] == 0
    assert outsider_client.get(f"/api/emissions/activities/{record['id']}/").status_code == 404
    assert outsider_client.get("/api/emissions/summary/").json()["total_kg_co2e"] == "0.00"
    assert totals_by_scope(other, date(2026, 1, 1), date(2027, 1, 1)) == {1: 0, 2: 0, 3: 0}


def test_filter_dates_and_consumers_use_real_totals(api_for, admin_user, factor, site):
    client = api_for(admin_user)
    for day in ["2026-01-01", "2026-01-31", "2026-02-01"]:
        assert (
            client.post("/api/emissions/activities/", payload(factor, site, date=day)).status_code
            == 201
        )
    params = {"start": "2026-01-01", "end": "2026-02-01", "scope": 2, "site": site.pk}
    assert client.get("/api/emissions/activities/", params).json()["count"] == 2
    summary = client.get("/api/emissions/summary/", params).json()
    assert summary["total_kg_co2e"] == "80.00"
    assert summary["demo_count"] == 2
    totals = emissions_data.totals_by_scope(
        admin_user.organisation, date(2026, 1, 1), date(2026, 2, 1)
    )
    assert totals == {1: Decimal("0"), 2: Decimal("80"), 3: Decimal("0")}
    assert all(isinstance(value, Decimal) for value in totals.values())
    snapshot = build_snapshot(admin_user.organisation, year=2026)
    assert snapshot.total == Decimal("120")


@pytest.mark.parametrize(
    "params",
    [
        {"start": "bad"},
        {"scope": 4},
        {"site": 999999},
        {"start": "2026-02-01", "end": "2026-01-01"},
        {"start": "2026-01-01", "end": "2026-01-01"},
    ],
)
def test_invalid_filters_return_400(api_for, viewer_user, params):
    client = api_for(viewer_user)
    for endpoint in ["activities", "summary"]:
        assert client.get(f"/api/emissions/{endpoint}/", params).status_code == 400


def test_factor_validation_and_permissions(api_for, admin_user, viewer_user):
    data = {
        "name": "Demo electricity",
        "scope": 2,
        "unit": "kWh",
        "kg_per_unit": "0.4",
        "source": "Synthetic example",
        "year": 2026,
        "is_demo": True,
    }
    client = api_for(admin_user)
    assert api_for(viewer_user).post("/api/emissions/factors/", data).status_code == 403
    for change in [{"scope": 4}, {"kg_per_unit": "-1"}, {"source": ""}, {"year": 10000}]:
        assert client.post("/api/emissions/factors/", data | change).status_code == 400
    response = client.post("/api/emissions/factors/", data)
    assert response.status_code == 201
    factor = EmissionFactor.objects.get()
    assert factor.organisation == admin_user.organisation
    assert AuditLog.objects.filter(action="create").count() == 1
    assert (
        client.patch(f"/api/emissions/factors/{factor.pk}/", {"kg_per_unit": "8"}).status_code
        == 405
    )


def test_saved_result_retains_factor_snapshot(api_for, admin_user, factor, site):
    client = api_for(admin_user)
    response = client.post("/api/emissions/activities/", payload(factor, site))
    factor.kg_per_unit = Decimal("0.8")
    factor.source = "Different source"
    factor.save()
    record = client.get(f"/api/emissions/activities/{response.json()['id']}/").json()
    assert record["kg_co2e"] == "40.00"
    assert record["factor_value"] == "0.40000000"
    assert record["factor_source"] == "Synthetic test factor"


def test_calculator_encapsulation_and_rounding():
    calculator = CO2eCalculator("0.4", "kWh")
    assert calculator.calculate("2.5125", "kWh") == Decimal("1.01")
    with pytest.raises(EmissionsError):
        calculator.set_factor("-1", "kWh")
    assert calculator.get_factor() == Decimal("0.4")
    assert calculator.get_unit() == "kWh"


def test_site_with_activities_cannot_be_deleted(api_for, admin_user, factor, site):
    client = api_for(admin_user)
    assert client.post("/api/emissions/activities/", payload(factor, site)).status_code == 201
    response = client.delete(f"/api/accounts/sites/{site.pk}/")
    assert response.status_code == 400
    assert "activity records" in str(response.json())
    assert Site.objects.filter(pk=site.pk).exists()
    assert not AuditLog.objects.filter(action="delete").exists()


def test_pagination_keeps_summary_total_for_all_records(api_for, admin_user, factor, site):
    client = api_for(admin_user)
    for index in range(21):
        assert (
            client.post(
                "/api/emissions/activities/", payload(factor, site, description=f"Record {index}")
            ).status_code
            == 201
        )
    first = client.get("/api/emissions/activities/").json()
    second = client.get("/api/emissions/activities/", {"page": 2}).json()
    assert len(first["results"]) == 20
    assert len(second["results"]) == 1
    assert first["count"] == second["count"] == 21
    assert first["next"] and second["previous"]
    assert not {row["id"] for row in first["results"]} & {row["id"] for row in second["results"]}
    assert client.get("/api/emissions/summary/").json()["total_kg_co2e"] == "840.00"
