"""Business rules for users, organisations, targets, alerts and audit history."""

import calendar
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from core import emissions_data

from .exceptions import InvalidTargetError, LastAdminError, SiteInUseError, WeakPasswordError
from .models import Alert, AuditLog, Organisation, ReductionTarget, User

AT_RISK_TOLERANCE = Decimal("1.10")


# Audit history -------------------------------------------------------------


def record_audit(*, actor, action, instance=None, organisation=None, changes=None):
    if organisation is None:
        organisation = getattr(instance, "organisation", None) or getattr(
            actor, "organisation", None
        )
    return AuditLog.objects.create(
        organisation=organisation,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=instance._meta.verbose_name.title() if instance is not None else "",
        object_id=str(instance.pk) if instance is not None and instance.pk else "",
        object_repr=str(instance)[:200] if instance is not None else "",
        changes=changes or {},
    )


def describe_changes(instance, new_values):
    """Return {field: {"from": old, "to": new}} for values that differ."""
    changes = {}
    for field, new in new_values.items():
        old = getattr(instance, field, None)
        if old != new:
            changes[field] = {"from": _plain(old), "to": _plain(new)}
    return changes


def _plain(value):
    return value if value is None or isinstance(value, (bool, int, str)) else str(value)


# Users and organisations ----------------------------------------------------


def check_password_strength(password, user):
    """Run Django's password validators; raise WeakPasswordError with their messages."""
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise WeakPasswordError(" ".join(exc.messages)) from exc


@transaction.atomic
def register_organisation(*, organisation_name, username, password, email="", **organisation):
    """Create a company together with its first administrator."""
    user = User(username=username, email=email, role=User.Role.ADMIN)
    check_password_strength(password, user)
    org = Organisation.objects.create(name=organisation_name, **organisation)
    user.organisation = org
    user.set_password(password)
    user.save()
    record_audit(actor=user, action=AuditLog.Action.CREATE, instance=org)
    return user


def create_member(*, organisation, password, **fields):
    user = User(organisation=organisation, **fields)
    check_password_strength(password, user)
    user.set_password(password)
    user.save()
    return user


def ensure_admin_remains(member, *, role=None, is_active=None):
    """Prevent an organisation from losing its last active administrator."""
    loses_admin = (role is not None and role != User.Role.ADMIN) or is_active is False
    if not (member.is_org_admin and member.is_active and loses_admin):
        return
    other_admins = User.objects.filter(
        organisation=member.organisation, role=User.Role.ADMIN, is_active=True
    ).exclude(pk=member.pk)
    if not other_admins.exists():
        raise LastAdminError()


@transaction.atomic
def delete_site(site, actor):
    """Delete a site with an audit entry; refuse if activity records still use it."""
    record_audit(actor=actor, action=AuditLog.Action.DELETE, instance=site)
    try:
        site.delete()
    except ProtectedError as exc:
        # The exception rolls back the transaction, so the audit entry is discarded too.
        raise SiteInUseError() from exc


# Targets and alerts ----------------------------------------------------------


def check_target(organisation, *, scope, baseline_year, target_year, exclude=None):
    """Raise InvalidTargetError unless the target's years work for this organisation."""
    if target_year <= baseline_year:
        raise InvalidTargetError("The target year must be after the baseline year.")
    duplicates = ReductionTarget.objects.filter(
        organisation=organisation, scope=scope, target_year=target_year
    )
    if exclude is not None:
        duplicates = duplicates.exclude(pk=exclude.pk)
    if duplicates.exists():
        raise InvalidTargetError("A target for this scope and year already exists.")


@dataclass(frozen=True)
class TargetProgress:
    reporting_year: int
    actual_kg_co2e: Decimal
    projected_kg_co2e: Decimal
    expected_kg_co2e: Decimal
    target_kg_co2e: Decimal
    reduction_achieved_percent: Decimal
    status: str

    NO_DATA = "no_data"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"

    def as_dict(self):
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


def target_progress(target: ReductionTarget, as_of: date | None = None) -> TargetProgress:
    """Compare this year's (projected) emissions to a linear path toward the target.

    The current year is extrapolated from the emissions recorded so far, so a target
    can be flagged before the year ends.
    """
    as_of = as_of or date.today()
    year = max(target.baseline_year, min(as_of.year, target.target_year))
    start, end = emissions_data.year_range(year)
    actual = emissions_data.total(
        emissions_data.totals_by_scope(target.organisation, start, end), target.scope
    )

    projected = actual
    if year == as_of.year:
        days_in_year = 366 if calendar.isleap(year) else 365
        elapsed = as_of.timetuple().tm_yday
        projected = actual * days_in_year / elapsed

    baseline = Decimal(target.baseline_kg_co2e)
    span = target.target_year - target.baseline_year
    expected = baseline - (baseline - target.target_kg_co2e) * (year - target.baseline_year) / span

    if actual == 0:
        status = TargetProgress.NO_DATA
    elif projected <= expected:
        status = TargetProgress.ON_TRACK
    elif projected <= expected * AT_RISK_TOLERANCE:
        status = TargetProgress.AT_RISK
    else:
        status = TargetProgress.OFF_TRACK

    cents = Decimal("0.01")
    return TargetProgress(
        reporting_year=year,
        actual_kg_co2e=actual.quantize(cents),
        projected_kg_co2e=projected.quantize(cents),
        expected_kg_co2e=expected.quantize(cents),
        target_kg_co2e=target.target_kg_co2e,
        reduction_achieved_percent=((baseline - projected) / baseline * 100).quantize(cents),
        status=status,
    )


def evaluate_targets(organisation, as_of: date | None = None) -> list[Alert]:
    """Create alerts for targets that are at risk or off track.

    An alert is not repeated while an unread alert of the same level exists.
    """
    levels = {
        TargetProgress.AT_RISK: Alert.Level.WARNING,
        TargetProgress.OFF_TRACK: Alert.Level.CRITICAL,
    }
    created = []
    for target in organisation.targets.all():
        progress = target_progress(target, as_of)
        level = levels.get(progress.status)
        if level is None:
            continue
        if target.alerts.filter(level=level, is_read=False).exists():
            continue
        message = (
            f"{target.get_scope_display()} target for {target.target_year} is "
            f"{progress.status.replace('_', ' ')}: projected {progress.projected_kg_co2e} kg "
            f"CO2e in {progress.reporting_year} vs. {progress.expected_kg_co2e} kg expected."
        )
        created.append(
            Alert.objects.create(
                organisation=organisation, target=target, level=level, message=message
            )
        )
    return created
