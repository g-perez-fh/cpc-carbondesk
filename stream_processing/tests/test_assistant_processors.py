"""Tests for the assistant processors: SavingsEstimator and HotspotRecommender."""

from datetime import datetime
from decimal import Decimal

import pytest

from stream_processing.assistant_processors import HotspotRecommender, SavingsEstimator
from stream_processing.base import ActivityEvent, EventSource
from stream_processing.emissions_processors import CO2eTransformer


def make_event(event_id, category, kg_co2e=None, quantity=0):
    return ActivityEvent(
        event_id=event_id,
        source="test",
        scope=3,
        category=category,
        quantity=Decimal(str(quantity)),
        unit="km",
        timestamp=datetime(2026, 1, 1),
        kg_co2e=kg_co2e,
    )


# SavingsEstimator -----------------------------------------------------------------------


def test_savings_estimator_annotates_known_categories():
    events = [
        make_event("a", "Flights", Decimal("2000")),
        make_event("b", "Unknown", Decimal("5000")),
        make_event("c", "Flights", None),
    ]
    result = list(SavingsEstimator({"Flights": "0.25"}).process(events))
    assert [e.event_id for e in result] == ["a", "b", "c"]
    assert result[0].metadata["savings_kg_co2e"] == Decimal("500.00")
    assert "savings_kg_co2e" not in result[1].metadata
    assert "savings_kg_co2e" not in result[2].metadata


@pytest.mark.parametrize("share", ["0", "-0.1", "1.5"])
def test_savings_estimator_validates_shares(share):
    with pytest.raises(ValueError):
        SavingsEstimator({"Flights": share})


# HotspotRecommender ------------------------------------------------------------------------


def test_recommender_waits_for_enough_events():
    events = [make_event(str(i), "Flights", Decimal("1")) for i in range(4)]
    assert list(HotspotRecommender(min_events=5).process(events)) == []


def test_recommender_flags_dominant_category_once():
    events = [make_event(str(i), "Flights", Decimal("3")) for i in range(5)]
    events += [make_event("x", "Freight", Decimal("1")), make_event("y", "Flights", Decimal("3"))]
    [rec] = list(HotspotRecommender(share_threshold="0.6", min_events=5).process(events))
    assert rec["category"] == "Flights"
    assert rec["share_percent"] == Decimal("100.0")
    assert "rail-first" in rec["suggestion"]


def test_recommender_can_flag_several_categories():
    events = [
        make_event("a", "Flights", Decimal("1")),
        make_event("b", "Freight", Decimal("1")),
        make_event("c", "Flights", Decimal("1")),
        make_event("d", "Freight", Decimal("1")),
    ]
    recs = list(HotspotRecommender(share_threshold="0.5", min_events=2).process(events))
    assert {rec["category"] for rec in recs} == {"Flights", "Freight"}


def test_recommender_uses_fallback_suggestion_and_skips_unconverted():
    events = [make_event("a", "Paper", Decimal("1")), make_event("b", "Paper", None)]
    [rec] = list(HotspotRecommender(min_events=1).process(events))
    assert rec["suggestion"] == "Review the largest Paper activities first."


@pytest.mark.parametrize("threshold, min_events", [("0", 5), ("1.2", 5), ("0.4", 0)])
def test_recommender_validates_arguments(threshold, min_events):
    with pytest.raises(ValueError):
        HotspotRecommender(share_threshold=threshold, min_events=min_events)


def test_full_pipeline_with_conversion():
    events = [make_event(str(i), "Flights", quantity=1000) for i in range(5)]
    pipeline = (
        EventSource(events)
        | CO2eTransformer({"Flights": Decimal("0.15")})
        | SavingsEstimator({"Flights": "0.2"})
        | HotspotRecommender(min_events=5)
    )
    [rec] = list(pipeline)
    assert rec["kg_co2e"] == Decimal("750.00")
