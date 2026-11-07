"""Small lazy pipeline for locally supplied operational telemetry."""

from abc import ABC, abstractmethod
from decimal import Decimal

from .calculations import CO2eCalculator, EmissionsError


class StreamProcessor(ABC):
    @abstractmethod
    def process(self, record):
        """Return a processed record, or None to filter it out."""

    def __add__(self, other):
        return Pipeline(self, other)


class Pipeline(StreamProcessor):
    def __init__(self, *processors):
        self.processors = processors

    def process(self, record):
        for processor in self.processors:
            if record is None:
                break
            record = processor.process(record)
        return record

    def run(self, records):
        for record in records:
            result = self.process(record)
            if result is not None:
                yield result


class ScopeFilter(StreamProcessor):
    def __init__(self, scopes):
        self.set_scopes(scopes)

    def get_scopes(self):
        return set(self._scopes)

    def set_scopes(self, scopes):
        values = set(scopes)
        if not values <= {1, 2, 3}:
            raise EmissionsError("Scopes must be 1, 2 or 3.")
        self._scopes = values

    def process(self, record):
        if record.get("scope") not in {1, 2, 3}:
            raise EmissionsError("Each event needs a valid scope.")
        return record if record["scope"] in self._scopes else None


class EmissionTransformer(StreamProcessor):
    def __init__(self, factors):
        self.factors = dict(factors)

    def process(self, record):
        try:
            factor = self.factors[record["factor"]]
            if factor["scope"] != record["scope"]:
                raise EmissionsError("Event scope does not match its factor.")
            kg = CO2eCalculator(factor["kg_per_unit"], factor["unit"]).calculate(
                record["quantity"], record["unit"]
            )
        except (KeyError, TypeError) as exc:
            raise EmissionsError("Event or factor is missing required fields.") from exc
        return dict(record, tonnes_co2e=kg / Decimal("1000"))


class ActivityStream:
    def __init__(self, events):
        self.events = iter(events)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.events)
