"""Plain-Python tests for the Hometask 1 accounts classes. No Django, no database."""

from datetime import date
from decimal import Decimal

import pytest

from accounts.domain import Organisation, ReductionTarget, User
from shared.models import ActivityRecord


def record(kg, year=2025, scope=1, organisation_id=1, site="Plant"):
    return ActivityRecord(
        organisation_id=organisation_id,
        site=site,
        date=date(year, 6, 15),
        scope=scope,
        category="Diesel",
        quantity=Decimal("1"),
        unit="l",
        factor_value=Decimal(str(kg)),
        kg_co2e=Decimal(str(kg)),
    )


# User ---------------------------------------------------------------------------------


def test_user_validates_attributes():
    with pytest.raises(ValueError):
        User("has spaces", organisation_id=1)
    with pytest.raises(ValueError):
        User("alice", organisation_id=0)
    with pytest.raises(ValueError):
        User("alice", organisation_id=1, role="owner")
    with pytest.raises(TypeError):
        User("alice", organisation_id=1, is_active="yes")


def test_user_permissions_follow_role():
    admin = User("alice", 1, role="admin").setup()
    viewer = User("victor", 1, role="viewer").setup()
    assert admin.is_admin and admin.can("manage_targets")
    assert viewer.can("read") and not viewer.can("enter_data")


def test_role_setter_updates_permissions():
    user = User("eddie", 1).setup()
    user.role = "editor"
    assert user.can("enter_data")


def test_inactive_user_can_do_nothing():
    user = User("alice", 1, role="admin").setup()
    user.is_active = False
    assert not user.is_admin and not user.can("read")


def test_user_setup_validates_permissions():
    assert not User("eddie", 1, role="editor").setup({"editor": {"read"}}).can("enter_data")
    with pytest.raises(ValueError):
        User("eddie", 1).setup({"owner": {"read"}})
    with pytest.raises(TypeError):
        User("eddie", 1).setup(["read"])


# Organisation -----------------------------------------------------------------------


def test_organisation_validates_attributes():
    assert Organisation(1, "  Acme GmbH ").name == "Acme GmbH"
    for kwargs in ({"id": 0, "name": "Acme"}, {"id": 1, "name": " "}, {"id": 1, "name": "x" * 201}):
        with pytest.raises(ValueError):
            Organisation(**kwargs)
    with pytest.raises(ValueError):
        Organisation(1, "Acme", employee_count=-1)
    with pytest.raises(TypeError):
        Organisation(1, "Acme", industry=None)


def test_organisation_setup_loads_sites_and_members():
    alice = User("alice", 1, role="admin").setup()
    organisation = Organisation(1, "Acme").setup(["HQ", "Plant"], [alice, User("bob", 1)])
    assert organisation.sites == ["HQ", "Plant"]
    assert organisation.admins() == [alice]
    with pytest.raises(ValueError):
        organisation.add_site("hq")


def test_organisation_rejects_foreign_or_duplicate_members():
    organisation = Organisation(1, "Acme").setup([], [User("alice", 1)])
    with pytest.raises(ValueError):
        organisation.add_member(User("eve", 2))
    with pytest.raises(ValueError):
        organisation.add_member(User("alice", 1))
    with pytest.raises(TypeError):
        organisation.add_member("alice")


def test_organisation_lists_cannot_be_changed_from_outside():
    organisation = Organisation(1, "Acme").setup(["HQ"])
    organisation.sites.append("Hacked")
    assert organisation.sites == ["HQ"]


def test_organisation_owns_only_its_activity_records():
    organisation = Organisation(1, "Acme")
    assert organisation.owns(record(10, organisation_id=1))
    assert not organisation.owns(record(10, organisation_id=2))
    assert not organisation.owns({"organisation_id": 1})


# ReductionTarget ----------------------------------------------------------------------


def make_target(**overrides):
    values = {
        "organisation_id": 1,
        "baseline_year": 2024,
        "baseline_kg_co2e": 1000,
        "target_year": 2028,
        "reduction_percent": 50,
    }
    return ReductionTarget(**{**values, **overrides})


def test_target_kg_is_derived_from_baseline():
    assert make_target().target_kg_co2e == Decimal("500.00")


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_year": 2024},
        {"baseline_year": 1800},
        {"baseline_kg_co2e": 0},
        {"reduction_percent": 0},
        {"reduction_percent": 101},
        {"scope": "4"},
        {"organisation_id": -1},
    ],
)
def test_target_rejects_invalid_values(overrides):
    with pytest.raises(ValueError):
        make_target(**overrides)


def test_target_years_stay_consistent_after_creation():
    target = make_target()
    with pytest.raises(ValueError):
        target.baseline_year = 2030
    with pytest.raises(ValueError):
        target.target_year = 2023


def test_expected_path_is_linear():
    target = make_target()
    assert target.expected_kg_co2e(2025) == Decimal("875.00")
    assert target.expected_kg_co2e(2035) == Decimal("500.00")


def test_setup_totals_kg_co2e_per_year_from_activity_records():
    target = make_target().setup([record(500), record(300), record(900, year=2026)])
    assert target.actual_kg_co2e(2025) == Decimal("800")
    assert target.actual_kg_co2e(2026) == Decimal("900")


def test_setup_ignores_other_organisations_and_scopes():
    target = make_target(scope="2").setup(
        [record(100, scope=2), record(5000, scope=1), record(7000, scope=2, organisation_id=9)]
    )
    assert target.actual_kg_co2e(2025) == Decimal("100")


def test_setup_rejects_non_activity_records():
    with pytest.raises(TypeError):
        make_target().setup([{"date": date(2025, 1, 1), "kg_co2e": 10}])


@pytest.mark.parametrize(
    "kg, status",
    [(800, "on_track"), (875, "on_track"), (950, "at_risk"), (990, "off_track")],
)
def test_status_compares_recorded_emissions_with_the_path(kg, status):
    assert make_target().setup([record(kg)]).status(2025) == status


def test_status_without_data():
    assert make_target().setup([]).status(2025) == "no_data"
