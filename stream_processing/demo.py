"""Demo: synthetic telemetry through the full Hometask 2 pipeline.

Run from the repository root with:

    python -m stream_processing.demo
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal

from .analytics_processors import PeakDetector, ScopeTotalsAggregator, WindowedKpi
from .base import ActivityEvent, EventSource
from .emissions_processors import CO2eTransformer, ScopeFilter

FACTORS = {
    "Flights": Decimal("0.15"),  # kg CO2e per passenger-km, scope 3
    "Datacenter power": Decimal("0.40"),  # kg CO2e per kWh, scope 2
    "Freight": Decimal("0.10"),  # kg CO2e per ton-km, scope 1
}

SOURCES = [
    ("flight", 3, "Flights", "km"),
    ("datacenter", 2, "Datacenter power", "kWh"),
    ("freight", 1, "Freight", "ton-km"),
]


def generate_sample_events(count=30, seed=42):
    """Yield synthetic telemetry mixing flight, data-center, and freight records."""
    rng = random.Random(seed)
    start = datetime(2026, 1, 1)
    for i in range(count):
        source, scope, category, unit = SOURCES[i % len(SOURCES)]
        quantity = Decimal(str(rng.randint(50, 500)))
        yield ActivityEvent(
            event_id=f"evt-{i}",
            source=source,
            scope=scope,
            category=category,
            quantity=quantity,
            unit=unit,
            timestamp=start + timedelta(minutes=i),
        )


def run_demo():
    source = EventSource(generate_sample_events(30))
    totals_pipeline = (
        source | ScopeFilter({1, 2, 3}) | CO2eTransformer(FACTORS) | ScopeTotalsAggregator()
    )
    final_totals = None
    for final_totals in totals_pipeline:
        pass
    print("Final totals by scope (tCO2e):")
    for scope, total in sorted(final_totals.items()):
        print(f"  Scope {scope}: {total:.4f} t")

    kpi_source = EventSource(generate_sample_events(30))
    kpi_pipeline = (
        kpi_source | ScopeFilter({1, 2, 3}) | CO2eTransformer(FACTORS) | WindowedKpi(window=10)
    )
    print("\nKPI snapshot every 10 events:")
    for snapshot in kpi_pipeline:
        print(f"  {snapshot}")

    peak_source = EventSource(generate_sample_events(30))
    peak_pipeline = (
        peak_source
        | ScopeFilter({1, 2, 3})
        | CO2eTransformer(FACTORS)
        | PeakDetector(threshold="0.05")
    )
    print("\nPeak events (>= 0.05 tCO2e):")
    for event in peak_pipeline:
        print(f"  {event.event_id} {event.category}: {event.tco2e:.4f} t")


if __name__ == "__main__":
    run_demo()
