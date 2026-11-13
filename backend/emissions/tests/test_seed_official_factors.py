"""First-run and rerun-safety behavior of the official-factor seed command.

The first-run test covers the seeded values and organisation ownership; the
remaining tests cover the rerun-safety rules: identical repeats are skipped and
conflicting factors abort the whole run without changing existing data. Rerun
assertions compare full stored state before and after the failed run, not
exception text.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import AuditLog, Organisation, Site
from emissions.management.commands.seed_official_factors import Command as SeedCommand
from emissions.models import ActivityRecord, EmissionFactor

pytestmark = pytest.mark.django_db

EXPECTED_FACTORS = {
    "Butane (tonnes)": {"unit": "tonnes", "kg_per_unit": Decimal("3033.38067")},
    "Butane (litres)": {"unit": "litres", "kg_per_unit": Decimal("1.74533")},
}


def create_organisation(name="Acme GmbH"):
    return Organisation.objects.create(name=name)


def run_seed(organisation):
    out = StringIO()
    call_command("seed_official_factors", "--organisation-id", str(organisation.pk), stdout=out)
    return out.getvalue().strip()


def create_custom_factor(organisation, name, kg_per_unit):
    kind = EXPECTED_FACTORS[name]
    return EmissionFactor.objects.create(
        organisation=organisation,
        name=name,
        scope=1,
        unit=kind["unit"],
        kg_per_unit=Decimal(kg_per_unit),
        source="Synthetic custom factor",
        year=2025,
        is_demo=False,
    )


def create_used_activity(organisation, factor):
    """Create one clearly synthetic activity that references the factor."""
    site = Site.objects.create(organisation=organisation, name="Synthetic demo site")
    quantity = Decimal("10.0000")
    return ActivityRecord.objects.create(
        organisation=organisation,
        site=site,
        factor=factor,
        description="Synthetic butane usage (demo fixture)",
        date=date(2025, 1, 31),
        quantity=quantity,
        category="Butane",
        scope=1,
        unit=factor.unit,
        factor_value=factor.kg_per_unit,
        factor_source=factor.source,
        factor_year=factor.year,
        is_demo=True,
        kg_co2e=(quantity * factor.kg_per_unit).quantize(Decimal("0.01")),
    )


def factor_snapshot(organisation):
    return [
        (f.pk, f.name, f.scope, f.unit, f.kg_per_unit, f.year, f.source, f.is_demo)
        for f in EmissionFactor.objects.filter(organisation=organisation).order_by("pk")
    ]


def activity_snapshot(activity):
    return (
        activity.pk,
        activity.quantity,
        activity.unit,
        activity.factor_value,
        activity.factor_source,
        activity.factor_year,
        activity.is_demo,
        activity.kg_co2e,
        activity.description,
    )


def assert_first_run_state(organisation):
    factors = list(EmissionFactor.objects.filter(organisation=organisation).order_by("name"))
    assert [f.name for f in factors] == ["Butane (litres)", "Butane (tonnes)"]
    for factor in factors:
        expected = EXPECTED_FACTORS[factor.name]
        assert factor.scope == 1
        assert factor.unit == expected["unit"]
        assert factor.kg_per_unit == expected["kg_per_unit"]
        assert factor.year == 2025
        assert factor.source == "UK Government GHG Conversion Factors for Company Reporting 2025"
        assert factor.is_demo is False


def test_first_run_seeds_reviewed_factors_into_selected_organisation_only():
    acme = create_organisation()
    other = create_organisation("Other Ltd")

    output = run_seed(acme)

    assert output == "Created 2; skipped 0 identical."
    assert_first_run_state(acme)
    assert EmissionFactor.objects.filter(organisation=other).count() == 0


def test_identical_repeat_run_keeps_factors_and_ids_unchanged():
    acme = create_organisation()
    assert run_seed(acme) == "Created 2; skipped 0 identical."
    before = factor_snapshot(acme)

    output = run_seed(acme)

    assert output == "Created 0; skipped 2 identical."
    assert factor_snapshot(acme) == before


def test_conflicting_custom_factor_fails_without_changes():
    acme = create_organisation()
    custom = create_custom_factor(acme, "Butane (tonnes)", "2000.00000000")
    before = factor_snapshot(acme)

    with pytest.raises(CommandError):
        run_seed(acme)

    # The custom factor keeps its identifier and every stored field.
    assert factor_snapshot(acme) == before
    assert EmissionFactor.objects.filter(pk=custom.pk, name="Butane (tonnes)").exists()
    # The conflict on the first dataset entry aborts before any new factor is created.
    assert EmissionFactor.objects.filter(organisation=acme).count() == 1


def test_conflict_on_used_factor_preserves_activity_snapshot_and_audits():
    acme = create_organisation()
    used = create_custom_factor(acme, "Butane (tonnes)", "2000.00000000")
    activity = create_used_activity(acme, used)
    factors_before = factor_snapshot(acme)
    activity_before = activity_snapshot(activity)
    audits_before = list(AuditLog.objects.all())

    with pytest.raises(CommandError):
        run_seed(acme)

    assert factor_snapshot(acme) == factors_before
    refreshed = ActivityRecord.objects.get(pk=activity.pk)
    assert activity_snapshot(refreshed) == activity_before
    # Seeding must never write audit history, only fail atomically.
    assert list(AuditLog.objects.all()) == audits_before
    assert AuditLog.objects.filter(organisation=acme).count() == 0
    # The litres factor from the dataset was never created.
    assert EmissionFactor.objects.filter(organisation=acme).count() == 1


def test_ambiguous_duplicate_name_year_fails_without_changes():
    acme = create_organisation()
    first = create_custom_factor(acme, "Butane (tonnes)", "2000.00000000")
    second = create_custom_factor(acme, "Butane (tonnes)", "2500.00000000")
    before = factor_snapshot(acme)

    with pytest.raises(CommandError):
        run_seed(acme)

    # Both ambiguous duplicates are detected and left exactly as they were.
    assert factor_snapshot(acme) == before
    assert {first.pk, second.pk} <= {f.pk for f in EmissionFactor.objects.filter(organisation=acme)}
    assert EmissionFactor.objects.filter(organisation=acme).count() == 2


def test_second_entry_conflict_rolls_back_first_insertion_atomically():
    acme = create_organisation()
    # The dataset creates tonnes before litres, so a litres conflict exposes
    # whether the first insertion is rolled back.
    create_custom_factor(acme, "Butane (litres)", "1.74532000")
    before = factor_snapshot(acme)

    with pytest.raises(CommandError):
        run_seed(acme)

    # No "Butane (tonnes)" insertion survived the failed seed.
    assert not EmissionFactor.objects.filter(organisation=acme, name="Butane (tonnes)").exists()
    assert factor_snapshot(acme) == before
    assert AuditLog.objects.filter(organisation=acme).count() == 0


def test_documented_invocation_matches_command_parser():
    """The documented 'seed_official_factors --organisation-id <ID>' line is the real interface."""

    command = SeedCommand()
    parser = command.create_parser("manage.py", "seed_official_factors")
    action = parser._option_string_actions["--organisation-id"]

    assert action.required is True
    assert action.dest == "organisation_id"
    assert "primary key" in action.help.lower()

    # Missing the required argument is rejected before any database write.
    with pytest.raises(CommandError):
        call_command("seed_official_factors")


def test_missing_required_organisation_id_performs_no_writes():
    create_organisation()

    with pytest.raises(CommandError):
        call_command("seed_official_factors")

    assert EmissionFactor.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_nonexistent_organisation_id_fails_without_writes():
    # No organisation exists in this test database, so the ID cannot match one.
    with pytest.raises(CommandError):
        call_command("seed_official_factors", "--organisation-id", "987654")

    assert EmissionFactor.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_two_organisations_seed_independently():
    acme = create_organisation("Acme GmbH")
    run_seed(acme)
    acme_after_first_seed = factor_snapshot(acme)
    other = create_organisation("Other Ltd")

    output = run_seed(other)

    assert output == "Created 2; skipped 0 identical."
    assert_first_run_state(other)
    # Separate ownership: disjoint primary keys, each organisation sees only its own rows.
    acme_pks = {f.pk for f in EmissionFactor.objects.filter(organisation=acme)}
    other_pks = {f.pk for f in EmissionFactor.objects.filter(organisation=other)}
    assert acme_pks and other_pks
    assert acme_pks.isdisjoint(other_pks)
    assert EmissionFactor.objects.count() == 4
    # The first organisation keeps its exact rows after the independent second seeding.
    assert factor_snapshot(acme) == acme_after_first_seed
