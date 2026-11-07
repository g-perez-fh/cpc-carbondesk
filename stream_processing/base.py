"""Shared stream-processing framework for Hometask 2 (Enterprise Carbon Footprint Tracker).

This file is the team's shared base: plain Python, no Django, no database. Every
subsystem's processors (emissions_processors.py, analytics_processors.py, and any
future ones) are StreamProcessor subclasses built on top of what's here.

Pipeline stages chain with the `|` operator, left to right:

    source | ScopeFilter({1, 2}) | CO2eTransformer(factors) | ScopeTotalsAggregator()

`source` can be any iterable or generator (typically an EventSource). Each stage is
a generator that lazily consumes the previous stage's output - nothing is buffered
in memory, so a pipeline can run over an endless stream of telemetry.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class ActivityEvent:
    """One piece of operational telemetry: a flight leg, a server power reading, a freight run.

    Field names match the shared ActivityRecord (backend.emissions.models.ActivityRecord /
    shared.models.ActivityRecord) wherever the same concept applies (scope, category,
    quantity, unit, site, kg_co2e), so the three subsystems never disagree on what these
    mean. Emissions are stored in kg CO2e; tco2e exposes the same value in metric tons,
    same as ActivityRecord. A raw event has no kg_co2e yet - CO2eTransformer fills it in
    once a scope and factor are known.
    """

    event_id: str
    source: str
    scope: int
    category: str
    quantity: Decimal
    unit: str
    timestamp: datetime
    site: str = ""
    kg_co2e: Decimal | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def tco2e(self) -> Decimal | None:
        """kg_co2e converted to metric tons CO2e, or None if not yet converted."""
        if self.kg_co2e is None:
            return None
        return self.kg_co2e / Decimal("1000")


class StreamProcessor(ABC):
    """Base class for every stage in a telemetry pipeline.

    Subclasses implement process(events): consume an iterable of ActivityEvent (or,
    for the final stage, whatever the previous stage yields) and yield results.
    process() must be a generator (or return one) so stages compose lazily.
    """

    @abstractmethod
    def process(self, events):
        raise NotImplementedError

    def __iter__(self):
        """Lets a processor or pipeline be consumed directly: `for row in pipeline: ...`."""
        return self.process(())

    def __or__(self, other):
        """processor | processor -> a Pipeline running self then other."""
        if not isinstance(other, StreamProcessor):
            return NotImplemented
        return Pipeline([self, other])

    def __ror__(self, events):
        """iterable | processor -> a Pipeline that starts from that iterable."""
        return Pipeline([_SourceStage(events), self])


class Pipeline(StreamProcessor):
    """An ordered chain of StreamProcessor stages, itself a StreamProcessor."""

    def __init__(self, stages):
        self.stages = list(stages)

    def process(self, events):
        stream = events
        for stage in self.stages:
            stream = stage.process(stream)
        yield from stream


class _SourceStage(StreamProcessor):
    """Wraps a plain iterable so it can be the first stage of a Pipeline."""

    def __init__(self, events):
        self._events = events

    def process(self, events):
        yield from self._events


class EventSource:
    """Exposes any iterable or generator of ActivityEvent through the iterator protocol."""

    def __init__(self, events):
        self._iterator = iter(events)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iterator)
