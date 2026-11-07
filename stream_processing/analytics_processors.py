"""Analytics subsystem (Harib): aggregation, rolling KPIs, and peak detection.

These stages run after ScopeFilter and CO2eTransformer, so every event they see
already has scope and kg_co2e set.
"""

from decimal import Decimal

from .base import StreamProcessor


class ScopeTotalsAggregator(StreamProcessor):
    """Running total of tCO2e per scope. Yields a snapshot dict after every event."""

    def __init__(self):
        self.totals = {}

    def process(self, events):
        for event in events:
            if event.kg_co2e is None:
                continue
            self.totals[event.scope] = self.totals.get(event.scope, Decimal("0")) + event.tco2e
            yield dict(self.totals)


class WindowedKpi(StreamProcessor):
    """Generator yielding a KPI snapshot (count, total, average tCO2e) every `window` events."""

    def __init__(self, window=10):
        if window <= 0:
            raise ValueError("window must be a positive integer")
        self.window = window

    def process(self, events):
        count = 0
        total = Decimal("0")
        for event in events:
            if event.kg_co2e is None:
                continue
            count += 1
            total += event.tco2e
            if count % self.window == 0:
                yield {
                    "events": count,
                    "total_tco2e": total,
                    "average_tco2e": (total / count).quantize(Decimal("0.0001")),
                }


class PeakDetector(StreamProcessor):
    """Flags (yields) events whose tCO2e is at or above a threshold."""

    def __init__(self, threshold):
        self.threshold = threshold if isinstance(threshold, Decimal) else Decimal(str(threshold))

    def process(self, events):
        for event in events:
            if event.kg_co2e is not None and event.tco2e >= self.threshold:
                yield event
