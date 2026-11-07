"""Validated emissions stages using the team's shared event and pipeline contract.

Factors are keyed by ActivityEvent.category and contain scope, unit and
kg_per_unit. Results remain ActivityEvent objects; tco2e is their shared
read-only conversion property. Unknown factors raise EmissionsError instead of
silently passing through uncalculated events.
"""

from dataclasses import replace

from stream_processing.base import EventSource, Pipeline, StreamProcessor

from .calculations import CO2eCalculator, EmissionsError

# Reuse the team's iterator rather than maintaining a second stream framework.
ActivityStream = EventSource
__all__ = ["ActivityStream", "EmissionTransformer", "Pipeline", "ScopeFilter", "StreamProcessor"]


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

    def process(self, events):
        for event in events:
            if event.scope not in {1, 2, 3}:
                raise EmissionsError("Each event needs a valid scope.")
            if event.scope in self._scopes:
                yield event


class EmissionTransformer(StreamProcessor):
    def __init__(self, factors):
        self._factors = {}
        for category, factor in factors.items():
            try:
                scope = factor["scope"]
                calculator = CO2eCalculator(factor["kg_per_unit"], factor["unit"])
            except (KeyError, TypeError) as exc:
                raise EmissionsError("Factor needs scope, unit and kg_per_unit.") from exc
            if scope not in {1, 2, 3}:
                raise EmissionsError("Factor scope must be 1, 2 or 3.")
            self._factors[category] = (scope, calculator)

    def process(self, events):
        for event in events:
            try:
                scope, calculator = self._factors[event.category]
            except KeyError as exc:
                raise EmissionsError(f"No factor for category '{event.category}'.") from exc
            if event.scope != scope:
                raise EmissionsError("Event scope does not match its factor.")
            result = calculator.calculate(event.quantity, event.unit)
            # Keep identity, organisation, date, site and telemetry metadata intact.
            # A fresh event allows another pipeline to reuse the original input.
            yield replace(event, factor_value=calculator.get_factor(), kg_co2e=result)
