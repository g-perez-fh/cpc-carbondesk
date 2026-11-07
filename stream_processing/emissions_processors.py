"""Emissions subsystem (Guillermo): scope filtering and the kg -> tCO2e conversion.

This is the core transformation the rest of the pipeline builds on. Extend here -
for example with per-site or per-year emission factors, or additional scope rules.
"""

from .base import StreamProcessor


class ScopeFilter(StreamProcessor):
    """Keep only events whose scope tag (1, 2, or 3) is in the given set."""

    def __init__(self, scopes):
        self.scopes = set(scopes)

    def process(self, events):
        for event in events:
            if event.scope in self.scopes:
                yield event


class CO2eTransformer(StreamProcessor):
    """Convert each event's quantity to kg CO2e using an emission factor.

    `factors` maps an event's category (e.g. "Flights", "Datacenter power") to a
    kg-CO2e-per-unit Decimal. Events whose category has no known factor pass through
    unchanged, with kg_co2e left as None, so later stages can filter them out. Use
    event.tco2e where a value in metric tons is needed.
    """

    def __init__(self, factors):
        self.factors = factors

    def process(self, events):
        for event in events:
            factor = self.factors.get(event.category)
            if factor is not None:
                event.kg_co2e = event.quantity * factor
            yield event
