"""Shared data model for one activity record, used across all CarbonDesk subsystems.

Every subsystem should read and write this shape instead of inventing its own.
Field names match the Django model backend.emissions.models.ActivityRecord, which
is the source of truth in the database; this plain dataclass is what the
framework-free parts of the codebase (backend/analytics/domain.py,
stream_processing/) pass around instead of ad-hoc dicts.

Emissions are always stored in kg CO2e (kg_co2e). Use the tco2e property where a
value in metric tons is needed for display.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(kw_only=True)
class ActivityRecord:
    organisation_id: int
    site: str
    date: date
    scope: int
    category: str
    quantity: Decimal
    unit: str
    factor_value: Decimal
    kg_co2e: Decimal
    id: int | None = None

    @property
    def tco2e(self) -> Decimal:
        """kg_co2e converted to metric tons CO2e."""
        return self.kg_co2e / Decimal("1000")
