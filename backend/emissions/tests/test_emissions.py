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
        == 200
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


@pytest.fixture
def saved_activity(api_for, admin_user, factor, site):
    return api_for(admin_user).post("/api/emissions/activities/", payload(factor, site)).json()


def test_edit_recalculates_and_keeps_audit_snapshots(api_for, editor_user, saved_activity):
    client = api_for(editor_user)
    response = client.patch(
        f"/api/emissions/activities/{saved_activity['id']}/",
        {"quantity": "250", "kg_co2e": "999"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["kg_co2e"] == "100.00"
    audit = AuditLog.objects.get(action="update")
    assert audit.actor == editor_user
    assert audit.changes["before"]["kg_co2e"] == "40.00"
    assert audit.changes["after"]["kg_co2e"] == "100.00"
    assert client.get("/api/analytics/dashboard/").json()["total_kg_co2e"] == "100.00"


def test_description_edit_preserves_saved_factor(api_for, admin_user, factor, saved_activity):
    factor.kg_per_unit = Decimal("5")
    factor.save()
    response = api_for(admin_user).patch(
        f"/api/emissions/activities/{saved_activity['id']}/", {"description": "Corrected"}
    )
    assert response.status_code == 200
    assert response.json()["factor_value"] == "0.40000000"
    assert response.json()["kg_co2e"] == "40.00"


def test_switch_factor_refreshes_snapshot(api_for, admin_user, organisation, saved_activity):
    factor = EmissionFactor.objects.create(
        organisation=organisation,
        name="Diesel",
        scope=1,
        unit="l",
        kg_per_unit="2",
        source="Another synthetic example",
        year=2025,
        is_demo=True,
    )
    response = api_for(admin_user).patch(
        f"/api/emissions/activities/{saved_activity['id']}/", {"factor": factor.pk, "unit": "l"}
    )
    assert response.status_code == 200
    assert response.json()["kg_co2e"] == "200.00"
    assert response.json()["scope"] == 1
    assert response.json()["factor_source"] == factor.source


@pytest.mark.parametrize("data", [{"quantity": "-1"}, {"unit": "wrong"}, {"date": "10000-01-01"}])
def test_invalid_edit_does_not_change_record(api_for, admin_user, saved_activity, data):
    response = api_for(admin_user).patch(f"/api/emissions/activities/{saved_activity['id']}/", data)
    assert response.status_code == 400
    assert ActivityRecord.objects.get(pk=saved_activity["id"]).kg_co2e == Decimal("40")
    assert not AuditLog.objects.filter(action="update").exists()


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_viewer_cannot_change_activity(api_for, viewer_user, saved_activity, method):
    response = getattr(api_for(viewer_user), method)(
        f"/api/emissions/activities/{saved_activity['id']}/", {}
    )
    assert response.status_code == 403
    assert ActivityRecord.objects.filter(pk=saved_activity["id"]).exists()


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_other_company_cannot_change_activity(api_for, saved_activity, method):
    other = Organisation.objects.create(name="Other")
    user = User.objects.create(username="other-editor", organisation=other, role="editor")
    response = getattr(api_for(user), method)(
        f"/api/emissions/activities/{saved_activity['id']}/", {}
    )
    assert response.status_code == 404
    assert ActivityRecord.objects.filter(pk=saved_activity["id"]).exists()


def test_delete_preserves_history_and_removes_totals(api_for, editor_user, saved_activity):
    client = api_for(editor_user)
    url = f"/api/emissions/activities/{saved_activity['id']}/"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    audit = AuditLog.objects.get(action="delete")
    assert audit.changes["before"] == saved_activity
    assert client.get("/api/emissions/summary/").json()["total_kg_co2e"] == "0.00"
    assert client.get("/api/analytics/dashboard/").json()["record_count"] == 0


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_audit_failure_rolls_back_mutation(
    api_for, admin_user, saved_activity, monkeypatch, method
):
    def fail(**kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr("emissions.views.record_audit", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        getattr(api_for(admin_user), method)(
            f"/api/emissions/activities/{saved_activity['id']}/", {"quantity": "200"}
        )
    assert ActivityRecord.objects.get(pk=saved_activity["id"]).kg_co2e == Decimal("40")


@pytest.fixture
def editor_user(make_member):
    return make_member("editor", User.Role.EDITOR)


def test_factor_correction_and_explicit_recalculation(api_for, admin_user, factor, saved_activity):
    client = api_for(admin_user)
    url = f"/api/emissions/factors/{factor.pk}/"
    corrected = client.patch(url, {"kg_per_unit": "0.8", "source": "Corrected source"}).json()
    record = ActivityRecord.objects.get(pk=saved_activity["id"])
    assert record.kg_co2e == Decimal("40")
    preview = client.post(
        "/api/emissions/preview/",
        {"activity": record.pk, "factor": factor.pk, "quantity": "100", "unit": "kWh"},
    )
    assert preview.json()["kg_co2e"] == "40.00"
    response = client.post(url + "recalculate/", {"factor": corrected}, format="json")
    assert response.status_code == 200, response.data
    assert response.json()["updated"] == 1
    record.refresh_from_db()
    assert record.kg_co2e == Decimal("80")
    assert record.factor_source == "Corrected source"
    audit = AuditLog.objects.get(changes__reason="factor_recalculation")
    assert audit.changes["before"]["kg_co2e"] == "40.00"
    assert audit.changes["after"]["kg_co2e"] == "80.00"
    assert (
        client.post(url + "recalculate/", {"factor": corrected}, format="json").json()["updated"]
        == 0
    )
    assert client.get("/api/analytics/dashboard/").json()["total_kg_co2e"] == "80.00"


@pytest.mark.parametrize("change", [{"unit": "l"}, {"scope": 1}, {"kg_per_unit": "-1"}])
def test_factor_invalid_correction(api_for, admin_user, factor, change):
    assert (
        api_for(admin_user).patch(f"/api/emissions/factors/{factor.pk}/", change).status_code == 400
    )


def test_factor_stale_confirmation(api_for, admin_user, factor):
    client = api_for(admin_user)
    url = f"/api/emissions/factors/{factor.pk}/"
    old = client.get(url).json()
    client.patch(url, {"kg_per_unit": "0.8"})
    assert client.post(url + "recalculate/", {"factor": old}, format="json").status_code == 409


@pytest.mark.parametrize("role", ["viewer", "foreign"])
def test_factor_write_permissions(api_for, viewer_user, make_member, factor, role):
    user = (
        viewer_user
        if role == "viewer"
        else make_member(
            "foreign", User.Role.ADMIN, Organisation.objects.create(name="Other factor company")
        )
    )
    client = api_for(user)
    url = f"/api/emissions/factors/{factor.pk}/"
    expected = 403 if role == "viewer" else 404
    assert client.patch(url, {"kg_per_unit": "1"}).status_code == expected
    assert client.post(url + "recalculate/", {}, format="json").status_code == expected


def test_recalculation_failure_rolls_back(api_for, admin_user, factor, saved_activity, monkeypatch):
    client = api_for(admin_user)
    url = f"/api/emissions/factors/{factor.pk}/"
    corrected = client.patch(url, {"kg_per_unit": "0.8"}).json()

    def fail(**kwargs):
        raise RuntimeError("Audit unavailable")

    # recalculate_factor_records now lives in services.py, so the audit hook
    # is patched in that module; the rollback behavior under test is unchanged.
    monkeypatch.setattr("emissions.services.record_audit", fail)
    with pytest.raises(RuntimeError):
        client.post(url + "recalculate/", {"factor": corrected}, format="json")
    assert ActivityRecord.objects.get(pk=saved_activity["id"]).kg_co2e == Decimal("40")


def test_summary_requires_authentication_and_membership(api_for, factor, site):
    assert APIClient().get("/api/emissions/summary/").status_code == 401
    memberless = User.objects.create_user(username="org-less")
    assert api_for(memberless).get("/api/emissions/summary/").status_code == 403


def test_summary_shape_units_and_empty_scope(api_for, admin_user, factor, site, saved_activity):
    response = api_for(admin_user).get("/api/emissions/summary/")
    assert response.status_code == 200
    summary = response.json()
    assert set(summary) == {"count", "demo_count", "total_kg_co2e", "by_scope", "unit"}
    assert summary["unit"] == "kg CO2e"
    assert summary["count"] == 1
    assert summary["demo_count"] == 1
    assert summary["total_kg_co2e"] == "40.00"
    assert set(summary["by_scope"]) == {"1", "2", "3"}
    assert summary["by_scope"]["2"] == "40.00"
    assert summary["by_scope"]["1"] == "0.00"

    # Empty-scope convention: a filtered window with no records is a valid,
    # all-zero answer, not an error.
    empty = (
        api_for(admin_user)
        .get("/api/emissions/summary/", {"start": "2030-01-01", "end": "2030-02-01"})
        .json()
    )
    assert empty["count"] == 0
    assert empty["demo_count"] == 0
    assert empty["total_kg_co2e"] == "0.00"
    assert empty["by_scope"] == {"1": "0.00", "2": "0.00", "3": "0.00"}
