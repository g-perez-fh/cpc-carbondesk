"""Plain-Python OOP model of the Users, Organisation & Targets subsystem (Hometask 1).

These classes mirror the accounts UML diagram. They have no Django imports and no
database access, so they can be imported and tested on their own. ReductionTarget
works on the project's shared shared.models.ActivityRecord - the same shape the
Django model, Analytics and stream_processing use - instead of its own format.
The Django models and services in models.py / services.py apply the same rules
in the web app.
"""

import re
from decimal import Decimal

from shared.models import ActivityRecord

ROLES = ("admin", "editor", "viewer")
SCOPES = ("all", "1", "2", "3")
MIN_YEAR = 1990
MAX_YEAR = 2100
AT_RISK_TOLERANCE = Decimal("1.10")
CENTS = Decimal("0.01")
USERNAME_PATTERN = re.compile(r"^[\w.@+-]{1,150}$")

DEFAULT_PERMISSIONS = {
    "admin": {"read", "enter_data", "manage_members", "manage_targets", "view_audit_log"},
    "editor": {"read", "enter_data"},
    "viewer": {"read"},
}


def _as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _check_positive_id(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _check_year(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or not MIN_YEAR <= value <= MAX_YEAR:
        raise ValueError(f"{name} must be a year between {MIN_YEAR} and {MAX_YEAR}")
    return value


class User:
    """A member of one organisation with one role that decides what they may do."""

    def __init__(self, username, organisation_id, role="viewer", is_active=True):
        self.username = username
        self.organisation_id = organisation_id
        self.role = role
        self.is_active = is_active
        self._permissions = {}

    def setup(self, permissions=None):
        """Load the role -> allowed actions configuration (defaults to DEFAULT_PERMISSIONS)."""
        config = DEFAULT_PERMISSIONS if permissions is None else permissions
        if not isinstance(config, dict):
            raise TypeError("permissions must be a dict of role -> actions")
        unknown = set(config) - set(ROLES)
        if unknown:
            raise ValueError(f"unknown roles in permissions: {sorted(unknown)}")
        self._permissions = {role: set(actions) for role, actions in config.items()}
        return self

    @property
    def username(self):
        return self._username

    @username.setter
    def username(self, value):
        if not isinstance(value, str) or not USERNAME_PATTERN.match(value):
            raise ValueError("username must be 1-150 letters, digits or @/./+/-/_")
        self._username = value

    @property
    def organisation_id(self):
        return self._organisation_id

    @organisation_id.setter
    def organisation_id(self, value):
        self._organisation_id = _check_positive_id("organisation_id", value)

    @property
    def role(self):
        return self._role

    @role.setter
    def role(self, value):
        if value not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        self._role = value

    @property
    def is_active(self):
        return self._is_active

    @is_active.setter
    def is_active(self, value):
        if not isinstance(value, bool):
            raise TypeError("is_active must be a bool")
        self._is_active = value

    @property
    def is_admin(self):
        return self.is_active and self.role == "admin"

    def can(self, action):
        """Whether this user may perform ``action``. Inactive users may do nothing."""
        return self.is_active and action in self._permissions.get(self.role, set())


class Organisation:
    """A company using CarbonDesk, with its sites and members."""

    def __init__(self, id, name, industry="", employee_count=None):
        self.id = id
        self.name = name
        self.industry = industry
        self.employee_count = employee_count
        self._sites = []
        self._members = []

    def setup(self, sites, members=()):
        """Load the site names and the User members of this organisation."""
        self._sites = []
        self._members = []
        for site in sites:
            self.add_site(site)
        for member in members:
            self.add_member(member)
        return self

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        self._id = _check_positive_id("id", value)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("name must be a non-empty string")
        if len(value) > 200:
            raise ValueError("name must be at most 200 characters")
        self._name = value.strip()

    @property
    def industry(self):
        return self._industry

    @industry.setter
    def industry(self, value):
        if not isinstance(value, str):
            raise TypeError("industry must be a string")
        self._industry = value.strip()

    @property
    def employee_count(self):
        return self._employee_count

    @employee_count.setter
    def employee_count(self, value):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ValueError("employee_count must be a non-negative integer or None")
        self._employee_count = value

    @property
    def sites(self):
        """Read-only copy of the site names; use add_site() to change them."""
        return list(self._sites)

    @property
    def members(self):
        return list(self._members)

    def add_site(self, name):
        """Add a site; names are the ``site`` values used in ActivityRecord."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("site name must be a non-empty string")
        if any(site.lower() == name.strip().lower() for site in self._sites):
            raise ValueError(f"a site named {name!r} already exists")
        self._sites.append(name.strip())

    def add_member(self, user):
        if not isinstance(user, User):
            raise TypeError("members must be User objects")
        if user.organisation_id != self.id:
            raise ValueError("user belongs to a different organisation")
        if any(member.username == user.username for member in self._members):
            raise ValueError(f"user {user.username!r} is already a member")
        self._members.append(user)

    def admins(self):
        return [member for member in self._members if member.is_admin]

    def owns(self, record):
        """Whether an ActivityRecord belongs to this organisation (data isolation)."""
        return isinstance(record, ActivityRecord) and record.organisation_id == self.id


class ReductionTarget:
    """Reduce emissions by a percentage of a baseline year by a target year."""

    def __init__(
        self,
        organisation_id,
        baseline_year,
        baseline_kg_co2e,
        target_year,
        reduction_percent,
        scope="all",
    ):
        self.organisation_id = organisation_id
        self.scope = scope
        self.baseline_year = baseline_year
        self.baseline_kg_co2e = baseline_kg_co2e
        self.target_year = target_year
        self.reduction_percent = reduction_percent
        self._yearly_kg = {}

    def setup(self, records):
        """Load ActivityRecords and total their kg_co2e per year for this target.

        Records of other organisations, or of other scopes for a scope target, are
        ignored, as the web app's data isolation requires.
        """
        self._yearly_kg = {}
        for record in records:
            if not isinstance(record, ActivityRecord):
                raise TypeError("records must be shared.models.ActivityRecord objects")
            if record.organisation_id != self.organisation_id:
                continue
            if self.scope != "all" and str(record.scope) != self.scope:
                continue
            year = record.date.year
            self._yearly_kg[year] = self._yearly_kg.get(year, Decimal("0")) + _as_decimal(
                record.kg_co2e
            )
        return self

    @property
    def organisation_id(self):
        return self._organisation_id

    @organisation_id.setter
    def organisation_id(self, value):
        self._organisation_id = _check_positive_id("organisation_id", value)

    @property
    def scope(self):
        return self._scope

    @scope.setter
    def scope(self, value):
        if value not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}")
        self._scope = value

    @property
    def baseline_year(self):
        return self._baseline_year

    @baseline_year.setter
    def baseline_year(self, value):
        _check_year("baseline_year", value)
        if getattr(self, "_target_year", None) is not None and value >= self._target_year:
            raise ValueError("baseline_year must be before target_year")
        self._baseline_year = value

    @property
    def target_year(self):
        return self._target_year

    @target_year.setter
    def target_year(self, value):
        _check_year("target_year", value)
        if value <= self.baseline_year:
            raise ValueError("target_year must be after baseline_year")
        self._target_year = value

    @property
    def baseline_kg_co2e(self):
        return self._baseline_kg_co2e

    @baseline_kg_co2e.setter
    def baseline_kg_co2e(self, value):
        amount = _as_decimal(value)
        if amount <= 0:
            raise ValueError("baseline_kg_co2e must be positive")
        self._baseline_kg_co2e = amount

    @property
    def reduction_percent(self):
        return self._reduction_percent

    @reduction_percent.setter
    def reduction_percent(self, value):
        percent = _as_decimal(value)
        if not Decimal("0") < percent <= Decimal("100"):
            raise ValueError("reduction_percent must be greater than 0 and at most 100")
        self._reduction_percent = percent

    @property
    def target_kg_co2e(self):
        """Read-only: emissions allowed in the target year."""
        return (self.baseline_kg_co2e * (1 - self.reduction_percent / 100)).quantize(CENTS)

    def actual_kg_co2e(self, year):
        return self._yearly_kg.get(year, Decimal("0"))

    def expected_kg_co2e(self, year):
        """Emissions allowed in ``year`` on a straight line from baseline to target."""
        year = min(max(year, self.baseline_year), self.target_year)
        span = self.target_year - self.baseline_year
        reduction = (self.baseline_kg_co2e - self.target_kg_co2e) * (year - self.baseline_year)
        return (self.baseline_kg_co2e - reduction / span).quantize(CENTS)

    def status(self, year):
        """``no_data``, ``on_track``, ``at_risk`` (within 10% of the path) or ``off_track``."""
        actual = self.actual_kg_co2e(year)
        if not actual:
            return "no_data"
        expected = self.expected_kg_co2e(year)
        if actual <= expected:
            return "on_track"
        if actual <= expected * AT_RISK_TOLERANCE:
            return "at_risk"
        return "off_track"
