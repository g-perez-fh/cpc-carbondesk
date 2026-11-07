"""Demo: synthetic telemetry through the full Hometask 2 pipeline.

Run from the repository root with:

    python -m stream_processing.demo
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal

from .accounts_processors import OrganisationFilter, TargetAlertProcessor
from .analytics_processors import PeakDetector, ScopeTotalsAggregator, WindowedKpi
from .assistant_processors import HotspotRecommender, SavingsEstimator
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

    run_accounts_and_assistant_demo()


def assign_organisations(events, organisation_ids=(1, 2)):
    """Spread events over several organisations, as a shared telemetry feed would."""
    for i, event in enumerate(events):
        event.organisation_id = organisation_ids[i % len(organisation_ids)]
        yield event


def run_accounts_and_assistant_demo():
    """Omotunde's stages: one company's stream, target alerts, savings and advice."""
    company_events = list(
        EventSource(assign_organisations(generate_sample_events(30)))
        | OrganisationFilter(organisation_id=1)
        | CO2eTransformer(FACTORS)
    )
    print(f"\nOrganisation 1 owns {len(company_events)} of 30 events.")

    print("Target alerts (yearly target 500 kg CO2e):")
    for alert in company_events | TargetAlertProcessor(target_kg_co2e="500"):
        print(
            f"  {alert['level']} at {alert['event_id']}: {alert['running_kg_co2e']:.2f} kg "
            f"= {alert['used_percent']}% of target"
        )

    shares = {"Flights": "0.15", "Datacenter power": "0.70", "Freight": "0.25"}
    savings = sum(
        event.metadata.get("savings_kg_co2e", 0)
        for event in company_events | SavingsEstimator(shares)
    )
    print(f"Estimated savings with all measures: {savings:.2f} kg CO2e")

    print("Assistant recommendations:")
    for rec in company_events | HotspotRecommender(share_threshold="0.4"):
        print(f"  {rec['category']} ({rec['share_percent']}% of emissions): {rec['suggestion']}")


if __name__ == "__main__":
    run_demo()
