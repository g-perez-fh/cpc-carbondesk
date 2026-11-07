"""Tests for the shared ActivityRecord data model."""

from datetime import date
from decimal import Decimal

from shared.models import ActivityRecord


def make_record(**overrides):
    fields = {
        "organisation_id": 1,
        "site": "Plant",
        "date": date(2026, 1, 15),
        "scope": 1,
        "category": "Diesel",
        "quantity": Decimal("10"),
        "unit": "l",
        "factor_value": Decimal("2.68"),
        "kg_co2e": Decimal("26.8"),
    }
    fields.update(overrides)
    return ActivityRecord(**fields)


def test_tco2e_converts_kg_to_metric_tons():
    record = make_record(kg_co2e=Decimal("1500"))
    assert record.tco2e == Decimal("1.5")


def test_id_defaults_to_none_for_a_record_not_yet_persisted():
    record = make_record()
    assert record.id is None


def test_id_can_be_set_for_a_persisted_record():
    record = make_record(id=42)
    assert record.id == 42
