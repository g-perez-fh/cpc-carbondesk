"""Stage-5 (row A07) additions: factor-recalculation scope and code-level use.

The update/delete endpoints and their audit snapshots are already covered by
``test_emissions.py``; this file adds what that file does not have: one
recalculation touches only the target factor's records, other factors' saved
totals keep the values they were calculated with, and the service function
behind the ``recalculate`` action is also callable directly from code.
"""

from decimal import Decimal

import pytest

from accounts.models import AuditLog, Site
from emissions.models import EmissionFactor
from emissions.services import create_activity, recalculate_factor_records

pytestmark = pytest.mark.django_db


def make_factor(organisation, name, kg_per_unit):
    return EmissionFactor.objects.create(
        organisation=organisation,
        name=name,
        scope=2,
        unit="kWh",
        kg_per_unit=kg_per_unit,
        source="Synthetic",
        year=2026,
        is_demo=True,
    )


@pytest.fixture
def two_factors_one_record_each(organisation, admin_user):
    factor_a = make_factor(organisation, "Grid", "0.4")
    factor_b = make_factor(organisation, "Steam", "0.6")
    site = Site.objects.create(organisation=organisation, name="Office")
    record_a = create_activity(
        organisation=organisation,
        created_by=admin_user,
        factor=factor_a,
        site=site,
        quantity=Decimal("100"),
        unit="kWh",
        description="From grid",
        date="2026-01-31",
    )
    record_b = create_activity(
        organisation=organisation,
        created_by=admin_user,
        factor=factor_b,
        site=site,
        quantity=Decimal("100"),
        unit="kWh",
        description="From steam",
        date="2026-03-31",
    )
    return factor_a, factor_b, record_a, record_b


def test_recalculation_touches_only_the_target_factor(
    two_factors_one_record_each,
):
    factor_a, _factor_b, record_a, record_b = two_factors_one_record_each
    factor_a.kg_per_unit = Decimal("0.8")
    factor_a.save()

    updated = recalculate_factor_records(
        organisation=record_a.organisation, factor=factor_a, actor=record_a.created_by
    )

    assert updated == 1
    record_a.refresh_from_db()
    record_b.refresh_from_db()
    assert record_a.kg_co2e == Decimal("80")
    assert record_a.factor_value == Decimal("0.8")
    # The other factor's saved totals keep their pre-correction values; no
    # audit entry is written for a record the recalculation did not touch.
    assert record_b.kg_co2e == Decimal("60")
    assert record_b.factor_value == Decimal("0.6")

    assert AuditLog.objects.filter(action="update").count() == 1
    audit = AuditLog.objects.get(changes__reason="factor_recalculation")
    assert audit.object_id == str(record_a.pk)
    # The audit history preserves the old values (Stage-5 commitment):
    # totals and factor snapshot before and after the correction.
    assert audit.changes["before"]["kg_co2e"] == "40.00"
    assert audit.changes["before"]["factor_value"] == "0.40000000"
    assert audit.changes["after"]["kg_co2e"] == "80.00"
    assert audit.changes["after"]["factor_value"] == "0.80000000"


def test_recalculate_action_reports_the_service_count(
    api_for, admin_user, two_factors_one_record_each
):
    factor_a, _factor_b, _record_a, _record_b = two_factors_one_record_each
    factor_a.kg_per_unit = Decimal("0.8")
    factor_a.save()

    client = api_for(admin_user)
    confirmed = client.get(f"/api/emissions/factors/{factor_a.pk}/").json()
    response = client.post(
        f"/api/emissions/factors/{factor_a.pk}/recalculate/",
        {"factor": confirmed},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.json() == {"updated": 1}
    assert AuditLog.objects.filter(changes__reason="factor_recalculation").count() == 1


def test_service_calculates_a_fresh_record_without_api(
    organisation, admin_user, two_factors_one_record_each
):
    """Direct code call: min and max of the count contract."""
    factor_a, factor_b, _record_a, _record_b = two_factors_one_record_each

    # No correction yet: recalculation is a no-op that reports zero changes.
    assert (
        recalculate_factor_records(organisation=organisation, factor=factor_a, actor=admin_user)
        == 0
    )
    assert AuditLog.objects.filter(action="update").count() == 0

    factor_b.kg_per_unit = Decimal("0.9")
    factor_b.save()
    assert (
        recalculate_factor_records(organisation=organisation, factor=factor_b, actor=admin_user)
        == 1
    )
