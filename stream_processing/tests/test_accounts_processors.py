"""Tests for the accounts processors: OrganisationFilter and TargetAlertProcessor."""

from datetime import datetime
from decimal import Decimal

import pytest

from stream_processing.accounts_processors import OrganisationFilter, TargetAlertProcessor
from stream_processing.base import ActivityEvent, EventSource
from stream_processing.emissions_processors import CO2eTransformer


def make_event(event_id, organisation_id=None, kg_co2e=None, quantity=0):
    return ActivityEvent(
        event_id=event_id,
        source="test",
        scope=1,
        category="Diesel",
        quantity=Decimal(str(quantity)),
        unit="l",
        timestamp=datetime(2026, 1, 1),
        organisation_id=organisation_id,
        kg_co2e=kg_co2e,
    )


# OrganisationFilter -----------------------------------------------------------------


def test_organisation_filter_keeps_only_one_company():
    events = [make_event("a", 1), make_event("b", 2), make_event("c", 1), make_event("d")]
    kept = list(OrganisationFilter(1).process(events))
    assert [event.event_id for event in kept] == ["a", "c"]


@pytest.mark.parametrize("organisation_id", [0, -1, "1", None, True])
def test_organisation_filter_validates_id(organisation_id):
    with pytest.raises(ValueError):
        OrganisationFilter(organisation_id)


def test_organisation_filter_is_lazy_on_an_endless_stream():
    def endless():
        i = 0
        while True:
            i += 1
            yield make_event(f"e{i}", organisation_id=i % 2 + 1)

    stream = OrganisationFilter(2).process(endless())
    assert [next(stream).event_id for _ in range(3)] == ["e1", "e3", "e5"]


# TargetAlertProcessor -----------------------------------------------------------------


def test_target_alert_warns_once_then_alerts_once():
    events = [make_event(name, kg_co2e=Decimal("3000")) for name in "abcde"]
    alerts = list(TargetAlertProcessor(target_kg_co2e=10000).process(events))
    assert [(a["level"], a["event_id"]) for a in alerts] == [("warning", "c"), ("critical", "d")]
    assert alerts[0]["used_percent"] == Decimal("90.0")
    assert alerts[1]["running_kg_co2e"] == Decimal("12000")


def test_target_alert_is_silent_within_target_and_skips_unconverted_events():
    events = [make_event("a", kg_co2e=Decimal("1000")), make_event("b", kg_co2e=None)]
    processor = TargetAlertProcessor(target_kg_co2e=10000)
    assert list(processor.process(events)) == []
    assert processor.running_kg_co2e == Decimal("1000")


def test_reaching_the_target_exactly_is_a_warning_not_a_breach():
    events = [make_event("a", kg_co2e=Decimal("10000"))]
    alerts = list(TargetAlertProcessor(target_kg_co2e=10000).process(events))
    assert [a["level"] for a in alerts] == ["warning"]


@pytest.mark.parametrize("target, ratio", [(0, "0.8"), (-5, "0.8"), (10, "0"), (10, "1")])
def test_target_alert_validates_arguments(target, ratio):
    with pytest.raises(ValueError):
        TargetAlertProcessor(target_kg_co2e=target, warning_ratio=ratio)


def test_full_pipeline_with_organisation_filter_and_target():
    events = [
        make_event("a", 1, quantity=2000),  # 4000 kg
        make_event("b", 2, quantity=9000),  # other company
        make_event("c", 1, quantity=2000),  # 8000 kg in total
    ]
    pipeline = (
        EventSource(events)
        | OrganisationFilter(1)
        | CO2eTransformer({"Diesel": Decimal("2")})
        | TargetAlertProcessor(target_kg_co2e=5000)
    )
    assert [(a["level"], a["event_id"]) for a in pipeline] == [
        ("warning", "a"),  # 4000 kg is 80% of the 5000 kg target
        ("critical", "c"),
    ]
