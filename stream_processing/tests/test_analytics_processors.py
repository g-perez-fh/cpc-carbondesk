"""Tests for the Analytics subsystem's ScopeTotalsAggregator, WindowedKpi, and PeakDetector."""

from datetime import datetime
from decimal import Decimal

import pytest

from stream_processing.analytics_processors import PeakDetector, ScopeTotalsAggregator, WindowedKpi
from stream_processing.base import ActivityEvent, EventSource
from stream_processing.emissions_processors import CO2eTransformer, ScopeFilter

FACTORS = {"Electricity": Decimal("0.4"), "Diesel": Decimal("2.0")}


def make_event(event_id, scope, category, quantity, kg_co2e=None):
    return ActivityEvent(
        event_id=event_id,
        source="test",
        scope=scope,
        category=category,
        quantity=Decimal(str(quantity)),
        unit="kWh",
        timestamp=datetime(2026, 1, 1),
        kg_co2e=kg_co2e,
    )


def test_scope_totals_aggregator_running_totals():
    events = [
        make_event("a", 1, "Diesel", 0, kg_co2e=Decimal("1000")),
        make_event("b", 1, "Diesel", 0, kg_co2e=Decimal("2000")),
        make_event("c", 2, "Electricity", 0, kg_co2e=Decimal("5000")),
    ]
    snapshots = list(ScopeTotalsAggregator().process(events))
    assert snapshots[-1] == {1: Decimal("3"), 2: Decimal("5")}
    assert snapshots[0] == {1: Decimal("1")}


def test_scope_totals_aggregator_skips_unconverted_events():
    events = [make_event("a", 1, "Unknown", 0, kg_co2e=None)]
    assert list(ScopeTotalsAggregator().process(events)) == []


def test_windowed_kpi_rejects_non_positive_window():
    with pytest.raises(ValueError):
        WindowedKpi(window=0)


def test_windowed_kpi_yields_every_n_events():
    events = [make_event(str(i), 1, "Diesel", 0, kg_co2e=Decimal("1000")) for i in range(5)]
    snapshots = list(WindowedKpi(window=2).process(events))
    assert [s["events"] for s in snapshots] == [2, 4]
    assert snapshots[0]["total_tco2e"] == Decimal("2")
    assert snapshots[0]["average_tco2e"] == Decimal("1")


def test_peak_detector_flags_events_at_or_above_threshold():
    events = [
        make_event("low", 1, "Diesel", 0, kg_co2e=Decimal("100")),
        make_event("high", 1, "Diesel", 0, kg_co2e=Decimal("5000")),
    ]
    flagged = list(PeakDetector(threshold="1").process(events))
    assert [e.event_id for e in flagged] == ["high"]


def test_peak_detector_accepts_decimal_or_string_threshold():
    assert PeakDetector(Decimal("1")).threshold == PeakDetector("1").threshold


def test_full_pipeline_chains_all_four_homework_concepts():
    """ABC + inheritance/polymorphism + __or__ chaining + iterator/generator stages,
    end to end: filter by scope, convert kg to tCO2e, then aggregate running totals."""
    events = [
        make_event("a", 1, "Diesel", 500),  # filtered out (scope 1 not requested)
        make_event("b", 2, "Electricity", 1000),
        make_event("c", 2, "Electricity", 2000),
    ]
    source = EventSource(events)
    pipeline = source | ScopeFilter({2}) | CO2eTransformer(FACTORS) | ScopeTotalsAggregator()
    *_, final = pipeline
    assert final == {2: Decimal("1.2")}
