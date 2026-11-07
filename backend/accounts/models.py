from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Organisation(models.Model):
    """A company using CarbonDesk. All company data is scoped to one organisation."""

    name = models.CharField(max_length=200)
    industry = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)
    employee_count = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Site(models.Model):
    """A location or business unit, describing the company structure."""

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="sites")
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "name"], name="unique_site_name_per_organisation"
            )
        ]

    def __str__(self):
        return self.name


class Department(models.Model):
    """A company department available for activity classification."""

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="departments"
    )
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "name"], name="unique_department_name_per_organisation"
            )
        ]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Project user. Members belong to one organisation with one role."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="members",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)

    @property
    def is_org_admin(self):
        return self.organisation_id is not None and self.role == self.Role.ADMIN

    @property
    def can_edit_data(self):
        return self.organisation_id is not None and self.role in {
            self.Role.ADMIN,
            self.Role.EDITOR,
        }


class ReductionTarget(models.Model):
    """Reduce emissions by a percentage of a baseline year by a target year."""

    class Scope(models.TextChoices):
        ALL = "all", "All scopes"
        SCOPE_1 = "1", "Scope 1"
        SCOPE_2 = "2", "Scope 2"
        SCOPE_3 = "3", "Scope 3"

    year_validators = [MinValueValidator(1990), MaxValueValidator(2100)]

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="targets")
    scope = models.CharField(max_length=3, choices=Scope.choices, default=Scope.ALL)
    baseline_year = models.PositiveSmallIntegerField(validators=year_validators)
    baseline_kg_co2e = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    target_year = models.PositiveSmallIntegerField(validators=year_validators)
    reduction_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("100"))],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_year", "scope"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "scope", "target_year"],
                name="unique_target_per_scope_and_year",
            ),
            models.CheckConstraint(
                condition=models.Q(target_year__gt=models.F("baseline_year")),
                name="target_year_after_baseline_year",
            ),
        ]

    def __str__(self):
        return f"{self.get_scope_display()}: -{self.reduction_percent}% by {self.target_year}"

    @property
    def target_kg_co2e(self):
        remaining = 1 - Decimal(self.reduction_percent) / 100
        return (Decimal(self.baseline_kg_co2e) * remaining).quantize(Decimal("0.01"))


class Alert(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="alerts")
    target = models.ForeignKey(
        ReductionTarget, on_delete=models.CASCADE, null=True, blank=True, related_name="alerts"
    )
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    message = models.CharField(max_length=300)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.message


class AuditLog(models.Model):
    """Append-only history of who changed what in an organisation."""

    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        LOGIN = "login", "Logged in"
        LOGOUT = "logout", "Logged out"

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, null=True, blank=True, related_name="audit_logs"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.actor} {self.action} {self.object_type} {self.object_repr}"
