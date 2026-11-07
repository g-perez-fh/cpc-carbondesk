"""Plain-Python OOP model of the AI Sustainability Assistant subsystem (Hometask 1).

These classes mirror the assistant UML diagram. They have no Django imports, no
database access and no OpenAI calls, so they can be imported and tested on their own.
Activity data always arrives as the shared shared.models.ActivityRecord (kg CO2e);
organisations and targets come from the accounts subsystem (accounts.domain), so the
assistant reads the same shapes as the rest of the project. Recommendations and chat
messages are the assistant's own outputs, not activity data, so they stay plain dicts.
"""

import re
from decimal import Decimal

from accounts.domain import Organisation, ReductionTarget
from shared.models import ActivityRecord

SCOPES = (1, 2, 3)
EFFORTS = ("low", "medium", "high")
ROLES = ("user", "assistant")
MAX_MESSAGE_LENGTH = 2000
CENTS = Decimal("0.01")
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

DEFAULT_CATALOGUE = [
    {"title": "Optimise heating", "scope": 1, "share": "0.10", "effort": "low"},
    {"title": "Electrify company vehicles", "scope": 1, "share": "0.25", "effort": "high"},
    {"title": "Switch to renewable electricity", "scope": 2, "share": "0.70", "effort": "low"},
    {"title": "LED lighting and smart controls", "scope": 2, "share": "0.08", "effort": "medium"},
    {"title": "Rail-first travel policy", "scope": 3, "share": "0.15", "effort": "low"},
    {"title": "Engage key suppliers", "scope": 3, "share": "0.10", "effort": "medium"},
]


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _check_records(records):
    records = list(records)
    if not all(isinstance(record, ActivityRecord) for record in records):
        raise TypeError("records must be shared.models.ActivityRecord objects")
    return records


def scope_totals(records):
    """kg CO2e per scope (1, 2, 3) for a list of ActivityRecords."""
    totals = {scope: Decimal("0") for scope in SCOPES}
    for record in _check_records(records):
        totals[record.scope] = totals.get(record.scope, Decimal("0")) + _as_decimal(record.kg_co2e)
    return totals


class RecommendationEngine:
    """Ranks reduction measures by their estimated yearly savings in kg CO2e."""

    def __init__(self, limit=5):
        self.limit = limit
        self.catalogue = []

    def setup(self, catalogue=None):
        """Load the catalogue of measures (defaults to DEFAULT_CATALOGUE)."""
        self.catalogue = DEFAULT_CATALOGUE if catalogue is None else catalogue
        return self

    @property
    def limit(self):
        return self._limit

    @limit.setter
    def limit(self, value):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        self._limit = value

    @property
    def catalogue(self):
        return list(self._catalogue)

    @catalogue.setter
    def catalogue(self, measures):
        if not isinstance(measures, list):
            raise TypeError("catalogue must be a list of measures")
        checked = []
        for measure in measures:
            share = _as_decimal(measure["share"])
            if measure["scope"] not in SCOPES:
                raise ValueError(f"measure scope must be one of {SCOPES}")
            if not Decimal("0") < share <= Decimal("1"):
                raise ValueError("measure share must be greater than 0 and at most 1")
            if measure["effort"] not in EFFORTS:
                raise ValueError(f"measure effort must be one of {EFFORTS}")
            checked.append({**measure, "share": share})
        self._catalogue = checked

    def recommend(self, records):
        """Measures with estimated savings for the given ActivityRecords, largest first."""
        totals = scope_totals(records)
        ranked = [
            {
                **measure,
                "savings_kg_co2e": (totals[measure["scope"]] * measure["share"]).quantize(CENTS),
            }
            for measure in self._catalogue
        ]
        ranked = [item for item in ranked if item["savings_kg_co2e"] > 0]
        ranked.sort(key=lambda item: item["savings_kg_co2e"], reverse=True)
        return ranked[: self.limit]


class ChatSession:
    """One user's conversation with the assistant, keeping a bounded history."""

    def __init__(self, user_id, title="", history_limit=12):
        self.user_id = user_id
        self.title = title
        self.history_limit = history_limit
        self._messages = []

    def setup(self, messages):
        """Load earlier messages, e.g. ``[{"role": "user", "content": "Hi"}]``."""
        self._messages = []
        for message in messages:
            self.add_message(message["role"], message["content"])
        return self

    @property
    def user_id(self):
        return self._user_id

    @user_id.setter
    def user_id(self, value):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("user_id must be a positive integer")
        self._user_id = value

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, value):
        if not isinstance(value, str):
            raise TypeError("title must be a string")
        if len(value) > 120:
            raise ValueError("title must be at most 120 characters")
        self._title = value.strip()

    @property
    def history_limit(self):
        return self._history_limit

    @history_limit.setter
    def history_limit(self, value):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("history_limit must be a positive integer")
        self._history_limit = value

    @property
    def messages(self):
        return [dict(message) for message in self._messages]

    def add_message(self, role, content):
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"content must be at most {MAX_MESSAGE_LENGTH} characters")
        self._messages.append({"role": role, "content": content.strip()})
        if not self.title and role == "user":
            self.title = content.strip()[:60]

    def recent_history(self):
        """The last ``history_limit`` messages, which are sent to the language model."""
        return self.messages[-self.history_limit :]


class MonthlySummaryBuilder:
    """Compares one month's emissions with the previous month and writes a summary."""

    def __init__(self, organisation_name, month):
        self.organisation_name = organisation_name
        self.month = month
        self._current = scope_totals([])
        self._previous = scope_totals([])

    def setup(self, records):
        """Load ActivityRecords; only this month and the previous month are used."""
        records = _check_records(records)
        year, month = (int(part) for part in self.month.split("-"))
        previous = (year - 1, 12) if month == 1 else (year, month - 1)
        self._current = scope_totals(
            r for r in records if (r.date.year, r.date.month) == (year, month)
        )
        self._previous = scope_totals(r for r in records if (r.date.year, r.date.month) == previous)
        return self

    @property
    def organisation_name(self):
        return self._organisation_name

    @organisation_name.setter
    def organisation_name(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("organisation_name must be a non-empty string")
        self._organisation_name = value.strip()

    @property
    def month(self):
        return self._month

    @month.setter
    def month(self, value):
        if not isinstance(value, str) or not MONTH_PATTERN.match(value):
            raise ValueError("month must look like 'YYYY-MM'")
        self._month = value

    def total_kg_co2e(self):
        return sum(self._current.values(), Decimal("0"))

    def change_percent(self):
        """Change against the previous month in percent, or None without a previous month."""
        previous = sum(self._previous.values(), Decimal("0"))
        if not previous:
            return None
        return ((self.total_kg_co2e() - previous) / previous * 100).quantize(Decimal("0.1"))

    def largest_scope(self):
        if not self.total_kg_co2e():
            return None
        return max(SCOPES, key=lambda scope: self._current[scope])

    def build(self):
        """Markdown summary text for the month."""
        heading = f"### {self.organisation_name}: {self.month}"
        if not self.total_kg_co2e():
            return f"{heading}\n\nNo emissions were recorded for this month."
        lines = [heading, "", f"Total emissions: **{self.total_kg_co2e():,.2f} kg CO2e**."]
        change = self.change_percent()
        if change is not None:
            direction = "down" if change < 0 else "up"
            lines.append(f"That is {direction} {abs(change)}% from the previous month.")
        scope = self.largest_scope()
        lines.append(f"The largest share came from Scope {scope} ({self._current[scope]:,.2f} kg).")
        return "\n".join(lines)


class AssistantService:
    """Answers questions about one organisation from its ActivityRecords and targets.

    The rule-based answer is what the web app falls back to when no language model
    is available; numbers always come from the data, never from the model.
    """

    def __init__(self, organisation, engine=None):
        self.organisation = organisation
        self.engine = engine if engine is not None else RecommendationEngine().setup()
        self._records = []
        self._targets = []

    def setup(self, records, targets=()):
        """Load ActivityRecords and ReductionTargets; other organisations' data is dropped."""
        self._records = [r for r in _check_records(records) if self.organisation.owns(r)]
        targets = list(targets)
        if not all(isinstance(target, ReductionTarget) for target in targets):
            raise TypeError("targets must be accounts.domain.ReductionTarget objects")
        self._targets = [t for t in targets if t.organisation_id == self.organisation.id]
        for target in self._targets:
            target.setup(self._records)
        return self

    @property
    def organisation(self):
        return self._organisation

    @organisation.setter
    def organisation(self, value):
        if not isinstance(value, Organisation):
            raise TypeError("organisation must be an accounts.domain.Organisation")
        self._organisation = value

    @property
    def engine(self):
        return self._engine

    @engine.setter
    def engine(self, value):
        if not isinstance(value, RecommendationEngine):
            raise TypeError("engine must be a RecommendationEngine")
        self._engine = value

    def records_for_year(self, year):
        return [record for record in self._records if record.date.year == year]

    def answer(self, question, year=None):
        """Markdown answer built from the data for ``year`` (default: the latest year)."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        if not self._records:
            return "No emissions have been recorded yet. Add activity data to get advice."
        year = year or max(record.date.year for record in self._records)
        records = self.records_for_year(year)
        totals = scope_totals(records)
        lines = [f"**{self.organisation.name}, emissions in {year}:**"]
        lines += [f"- Scope {scope}: {kg:,.2f} kg CO2e" for scope, kg in totals.items()]
        for target in self._targets:
            lines.append(
                f"- Target scope {target.scope}, {target.target_year}: "
                f"{target.status(year).replace('_', ' ')}"
            )
        for measure in self.engine.recommend(records)[:3]:
            lines.append(
                f"- Suggestion: {measure['title']} (about "
                f"{measure['savings_kg_co2e']:,.2f} kg CO2e per year)"
            )
        return "\n".join(lines)

    def monthly_summary(self, month):
        """Summary text for ``month`` ('YYYY-MM') using MonthlySummaryBuilder."""
        return MonthlySummaryBuilder(self.organisation.name, month).setup(self._records).build()
