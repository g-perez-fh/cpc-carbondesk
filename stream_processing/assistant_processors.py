"""AI Sustainability Assistant subsystem (Omotunde): savings estimates and hotspot advice.

Both stages run after CO2eTransformer, so the events they see already have kg_co2e
set. Like the web app, numbers are calculated by rules here, not by AI, and stay in
kg CO2e as in the shared ActivityRecord.
"""

from decimal import Decimal

from .base import StreamProcessor

DEFAULT_SUGGESTIONS = {
    "Flights": "Introduce a rail-first travel policy and replace routine trips with video calls.",
    "Datacenter power": "Move servers to a renewable electricity tariff or a greener host.",
    "Freight": "Bundle shipments and switch short routes to electric or rail freight.",
}


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


class SavingsEstimator(StreamProcessor):
    """Annotate each event with the kg CO2e a typical reduction measure could save.

    ``reduction_shares`` maps a category to the share (0-1] of its emissions a measure
    avoids. The estimate goes into ``event.metadata["savings_kg_co2e"]``; events
    without a share or without kg_co2e pass through unchanged.
    """

    def __init__(self, reduction_shares):
        self.reduction_shares = {}
        for category, share in reduction_shares.items():
            share = _as_decimal(share)
            if not Decimal("0") < share <= Decimal("1"):
                raise ValueError(f"share for {category!r} must be greater than 0 and at most 1")
            self.reduction_shares[category] = share

    def process(self, events):
        for event in events:
            share = self.reduction_shares.get(event.category)
            if share is not None and event.kg_co2e is not None:
                event.metadata["savings_kg_co2e"] = event.kg_co2e * share
            yield event


class HotspotRecommender(StreamProcessor):
    """Yield a recommendation when one category causes a large share of emissions.

    After ``min_events`` converted events, a category whose share of the running
    kg_co2e total reaches ``share_threshold`` triggers one recommendation (once per
    category).
    """

    def __init__(self, share_threshold="0.4", min_events=5, suggestions=None):
        self.share_threshold = _as_decimal(share_threshold)
        if not Decimal("0") < self.share_threshold <= Decimal("1"):
            raise ValueError("share_threshold must be greater than 0 and at most 1")
        if not isinstance(min_events, int) or min_events < 1:
            raise ValueError("min_events must be a positive integer")
        self.min_events = min_events
        self.suggestions = DEFAULT_SUGGESTIONS if suggestions is None else suggestions

    def process(self, events):
        totals = {}
        count = 0
        recommended = set()
        for event in events:
            if event.kg_co2e is None:
                continue
            count += 1
            totals[event.category] = totals.get(event.category, Decimal("0")) + event.kg_co2e
            overall = sum(totals.values(), Decimal("0"))
            if count < self.min_events or not overall:
                continue
            for category, kg in totals.items():
                share = kg / overall
                if category not in recommended and share >= self.share_threshold:
                    recommended.add(category)
                    yield {
                        "category": category,
                        "share_percent": (share * 100).quantize(Decimal("0.1")),
                        "kg_co2e": kg,
                        "suggestion": self.suggestions.get(
                            category, f"Review the largest {category} activities first."
                        ),
                    }
