from datetime import datetime
from decimal import Decimal

import pytest

from emissions.calculations import EmissionsError
from emissions.streaming import ActivityStream, EmissionTransformer, ScopeFilter
from shared.models import ActivityRecord
from stream_processing.accounts_processors import OrganisationFilter, TargetAlertProcessor
from stream_processing.analytics_processors import ScopeTotalsAggregator
from stream_processing.assistant_processors import SavingsEstimator
from stream_processing.base import ActivityEvent, EventSource, StreamProcessor


def event(**changes):
    values = dict(
        event_id="meter-1",
        source="demo",
        timestamp=datetime(2026, 1, 1),
        organisation_id=1,
        site="Office",
        scope=2,
        category="Power",
        quantity=Decimal("100"),
        unit="kWh",
        metadata={"demo": True},
    )
    return ActivityEvent(**(values | changes))


def transformer():
    return EmissionTransformer({"Power": {"scope": 2, "unit": "kWh", "kg_per_unit": "0.4"}})


def test_shared_contract_and_analytics_integration():
    original = event()
    pipeline = ActivityStream([original]) | ScopeFilter([2]) | transformer()
    result = next(iter(pipeline))
    assert isinstance(result, ActivityRecord)
    assert isinstance(result, ActivityEvent)
    assert result.factor_value == Decimal("0.4")
    assert result.kg_co2e == Decimal("40.00")
    assert result.tco2e == Decimal("0.04")
    assert result.organisation_id == 1 and result.event_id == original.event_id
    assert result.metadata == original.metadata and result.site == "Office"
    assert original.kg_co2e is None
    totals = list([original] | transformer() | ScopeTotalsAggregator())
    assert totals == [{2: Decimal("0.04")}]
    assert ActivityStream is EventSource
    assert isinstance(transformer(), StreamProcessor)


def test_pipeline_is_lazy_and_filters_before_calculating():
    consumed = []

    def source():
        for scope in [1, 2, 2]:
            consumed.append(scope)
            yield event(scope=scope)

    stream = ActivityStream(source())
    pipeline = stream | ScopeFilter([2]) | transformer()
    assert consumed == []
    iterator = iter(pipeline)
    assert next(iterator).kg_co2e == Decimal("40")
    assert consumed == [1, 2]
    assert len(list(iterator)) == 1
    with pytest.raises(StopIteration):
        next(stream)


def test_shared_accounts_and_assistant_integration():
    # The other company's unknown category must be filtered before calculation.
    events = [event(), event(organisation_id=2, category="Unknown")]
    results = list(
        events
        | OrganisationFilter(1)
        | ScopeFilter([2])
        | transformer()
        | SavingsEstimator({"Power": "0.25"})
    )
    assert len(results) == 1
    assert results[0].metadata["savings_kg_co2e"] == Decimal("10.00")
    alerts = list(results | TargetAlertProcessor(target_kg_co2e="50"))
    assert len(alerts) == 1
    assert alerts[0]["level"] == "warning"
    assert alerts[0]["running_kg_co2e"] == Decimal("40.00")


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "l"},
        {"scope": 1},
        {"category": "Unknown"},
        {"quantity": Decimal("-1")},
        {"quantity": Decimal("NaN")},
    ],
)
def test_invalid_events_fail_explicitly(changes):
    with pytest.raises(EmissionsError):
        list([event(**changes)] | transformer())


def test_configuration_and_rounding():
    selected = ScopeFilter([2])
    with pytest.raises(EmissionsError):
        selected.set_scopes([4])
    selected.get_scopes().clear()
    assert selected.get_scopes() == {2}
    with pytest.raises(EmissionsError):
        list([event(scope=4)] | selected)
    with pytest.raises(EmissionsError):
        EmissionTransformer({"Power": {}})
    result = list([event(quantity=Decimal("2.5125"))] | transformer())[0]
    assert result.kg_co2e == Decimal("1.01")
    assert list([] | transformer()) == []


def test_csv_text_accessors():
    from emissions.csv_import import CsvImporter

    importer = CsvImporter("original", sites_by_name={}, factors_by_name={})
    importer.set_text("replacement")
    with pytest.raises(EmissionsError):
        importer.set_text(None)
    assert importer.get_text() == "replacement"
