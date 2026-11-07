"""Users, Organisation & Targets subsystem (Omotunde): data isolation and target alerts.

OrganisationFilter can run first in a pipeline. TargetAlertProcessor runs after
CO2eTransformer, so the events it sees already have kg_co2e set. Both work on the
shared ActivityEvent fields (organisation_id, kg_co2e) and stay in kg CO2e.
"""

from decimal import Decimal

from .base import StreamProcessor


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


class OrganisationFilter(StreamProcessor):
    """Keep only the events of one organisation (``event.organisation_id``).

    This is the streaming version of the web app's rule that a company never sees
    another company's data. Events without an organisation are dropped.
    """

    def __init__(self, organisation_id):
        if (
            not isinstance(organisation_id, int)
            or isinstance(organisation_id, bool)
            or organisation_id <= 0
        ):
            raise ValueError("organisation_id must be a positive integer")
        self.organisation_id = organisation_id

    def process(self, events):
        for event in events:
            if event.organisation_id == self.organisation_id:
                yield event


class TargetAlertProcessor(StreamProcessor):
    """Flag when running kg_co2e passes what a reduction target allows for the year.

    ``target_kg_co2e`` is the yearly budget from a ReductionTarget. One ``warning``
    alert is yielded when the running total first reaches ``warning_ratio`` of it,
    and one ``critical`` alert when it is first exceeded.
    """

    def __init__(self, target_kg_co2e, warning_ratio="0.8"):
        self.target_kg_co2e = _as_decimal(target_kg_co2e)
        self.warning_ratio = _as_decimal(warning_ratio)
        if self.target_kg_co2e <= 0:
            raise ValueError("target_kg_co2e must be positive")
        if not Decimal("0") < self.warning_ratio < Decimal("1"):
            raise ValueError("warning_ratio must be between 0 and 1")
        self.running_kg_co2e = Decimal("0")

    def _alert(self, level, event):
        used = self.running_kg_co2e / self.target_kg_co2e * 100
        return {
            "level": level,
            "event_id": event.event_id,
            "running_kg_co2e": self.running_kg_co2e,
            "target_kg_co2e": self.target_kg_co2e,
            "used_percent": used.quantize(Decimal("0.1")),
        }

    def process(self, events):
        warned = exceeded = False
        for event in events:
            if event.kg_co2e is None:
                continue
            self.running_kg_co2e += event.kg_co2e
            if not warned and self.running_kg_co2e >= self.target_kg_co2e * self.warning_ratio:
                warned = True
                yield self._alert("warning", event)
            if not exceeded and self.running_kg_co2e > self.target_kg_co2e:
                exceeded = True
                yield self._alert("critical", event)
