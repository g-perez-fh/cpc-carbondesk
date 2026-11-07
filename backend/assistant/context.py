"""Collect the company data the assistant is allowed to reason about."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from accounts.services import TargetProgress, target_progress
from core import emissions_data

from .exceptions import InvalidPeriodError
from .recommendations import Recommendation, recommend

MIN_YEAR = 2
MAX_YEAR = 9998


@dataclass
class TargetSummary:
    label: str
    progress: TargetProgress


@dataclass
class CompanySnapshot:
    organisation_name: str
    industry: str
    employee_count: int | None
    year: int
    totals: dict[int, Decimal]
    previous_totals: dict[int, Decimal]
    targets: list[TargetSummary] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return emissions_data.total(self.totals)

    @property
    def previous_total(self) -> Decimal:
        return emissions_data.total(self.previous_totals)

    @property
    def has_data(self) -> bool:
        return self.total > 0

    def to_prompt(self) -> str:
        """Compact plain-text description of the data for the language model."""
        lines = [
            f"Company: {self.organisation_name}",
            f"Industry: {self.industry or 'not specified'}",
            f"Employees: {self.employee_count or 'not specified'}",
            f"Emissions in {self.year} so far (kg CO2e): "
            + ", ".join(f"Scope {s}: {v:.2f}" for s, v in self.totals.items())
            + f", total: {self.total:.2f}",
            f"Emissions in {self.year - 1} (kg CO2e): total {self.previous_total:.2f}",
        ]
        if not self.has_data:
            lines.append("No emission activities have been recorded for this year yet.")
        for target in self.targets:
            p = target.progress
            lines.append(
                f"Target {target.label}: status {p.status}, projected {p.projected_kg_co2e} vs "
                f"expected {p.expected_kg_co2e} kg in {p.reporting_year}, "
                f"final target {p.target_kg_co2e} kg"
            )
        for rec in self.recommendations:
            lines.append(
                f"Recommended measure (Scope {rec.scope}, {rec.effort} effort): {rec.title} - "
                f"estimated saving {rec.estimated_savings_kg_co2e} kg CO2e per year"
            )
        return "\n".join(lines)


def build_snapshot(organisation, year: int | None = None, as_of: date | None = None):
    as_of = as_of or date.today()
    year = year or as_of.year
    # The previous year and next January must also be valid dates.
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise InvalidPeriodError(f"Enter a year between {MIN_YEAR} and {MAX_YEAR}.")
    totals = emissions_data.totals_by_scope(organisation, *emissions_data.year_range(year))
    previous = emissions_data.totals_by_scope(organisation, *emissions_data.year_range(year - 1))
    targets = [
        TargetSummary(label=str(target), progress=target_progress(target, as_of))
        for target in organisation.targets.all()
    ]
    return CompanySnapshot(
        organisation_name=organisation.name,
        industry=organisation.industry,
        employee_count=organisation.employee_count,
        year=year,
        totals=totals,
        previous_totals=previous,
        targets=targets,
        recommendations=recommend(totals),
    )
