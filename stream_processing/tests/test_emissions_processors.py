"""Tests for the Emissions subsystem's ScopeFilter and CO2eTransformer."""

from datetime import datetime
from decimal import Decimal

from stream_processing.base import ActivityEvent
from stream_processing.emissions_processors import CO2eTransformer, ScopeFilter


def make_event(scope, category, quantity):
    return ActivityEvent(
        event_id=f"{category}-{quantity}",
        source="test",
        scope=scope,
        category=category,
        quantity=Decimal(str(quantity)),
        unit="kWh",
        timestamp=datetime(2026, 1, 1),
    )


def test_scope_filter_keeps_only_selected_scopes():
    events = [
        make_event(1, "Diesel", 10),
        make_event(2, "Electricity", 20),
        make_event(3, "Flights", 30),
    ]
    kept = list(ScopeFilter({1, 3}).process(events))
    assert [e.scope for e in kept] == [1, 3]


def test_scope_filter_with_empty_set_keeps_nothing():
    events = [make_event(1, "Diesel", 10)]
    assert list(ScopeFilter(set()).process(events)) == []


def test_co2e_transformer_sets_kg_co2e_and_tco2e():
    factors = {"Electricity": Decimal("0.4")}
    event = make_event(2, "Electricity", 1000)
    (result,) = list(CO2eTransformer(factors).process([event]))
    assert result.kg_co2e == Decimal("400")
    assert result.tco2e == Decimal("0.4")


def test_co2e_transformer_leaves_unknown_categories_unconverted():
    event = make_event(2, "Unknown fuel", 100)
    (result,) = list(CO2eTransformer({}).process([event]))
    assert result.kg_co2e is None
    assert result.tco2e is None


def test_scope_filter_then_transformer_chain_via_pipe():
    factors = {"Electricity": Decimal("0.4")}
    events = [make_event(2, "Electricity", 1000), make_event(1, "Diesel", 500)]
    pipeline = events | ScopeFilter({2}) | CO2eTransformer(factors)
    (result,) = list(pipeline)
    assert result.scope == 2
    assert result.kg_co2e == Decimal("400")
    assert result.tco2e == Decimal("0.4")
