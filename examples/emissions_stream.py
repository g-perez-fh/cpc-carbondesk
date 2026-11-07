"""Run: PYTHONPATH=backend:. python examples/emissions_stream.py."""

from datetime import datetime
from decimal import Decimal

from emissions.streaming import ActivityStream, EmissionTransformer, ScopeFilter
from stream_processing.analytics_processors import ScopeTotalsAggregator
from stream_processing.base import ActivityEvent


def main():
    factors = {"Power": {"scope": 2, "unit": "kWh", "kg_per_unit": "0.4"}}
    events = [
        ActivityEvent(
            event_id="demo-1",
            source="synthetic",
            timestamp=datetime(2026, 1, 1),
            organisation_id=1,
            site="Demo office",
            scope=2,
            category="Power",
            quantity=Decimal("100"),
            unit="kWh",
        ),
    ]
    pipeline = ActivityStream(events) | ScopeFilter([2]) | EmissionTransformer(factors)
    for result in pipeline:
        print(result.event_id, result.kg_co2e, "kg CO2e;", result.tco2e, "tonnes CO2e")
    totals = events | EmissionTransformer(factors) | ScopeTotalsAggregator()
    print("Shared analytics totals:", list(totals))


if __name__ == "__main__":
    main()
