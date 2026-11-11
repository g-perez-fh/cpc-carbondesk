"""Company-owned factors and the activities calculated with them."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class EmissionFactor(models.Model):
    class Scope(models.IntegerChoices):
        DIRECT = 1, "Scope 1"
        ENERGY = 2, "Scope 2"
        INDIRECT = 3, "Scope 3"

    organisation = models.ForeignKey("accounts.Organisation", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    scope = models.PositiveSmallIntegerField(choices=Scope.choices)
    unit = models.CharField(max_length=30)
    kg_per_unit = models.DecimalField(
        max_digits=16, decimal_places=8, validators=[MinValueValidator(Decimal("0"))]
    )
    source = models.CharField(max_length=240)
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(9999)]
    )
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "-year", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kg_per_unit__gte=0), name="factor_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(scope__in=[1, 2, 3]), name="factor_valid_scope"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.year})"


class ActivityRecord(models.Model):
    organisation = models.ForeignKey("accounts.Organisation", on_delete=models.CASCADE)
    site = models.ForeignKey("accounts.Site", on_delete=models.PROTECT)
    factor = models.ForeignKey(EmissionFactor, on_delete=models.PROTECT)
    department = models.ForeignKey(
        "accounts.Department", on_delete=models.PROTECT, null=True, blank=True
    )
    description = models.CharField(max_length=160)
    date = models.DateField()
    quantity = models.DecimalField(
        max_digits=14, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    # Store the calculation inputs as well as the result so history remains explainable.
    category = models.CharField(max_length=100)
    scope = models.PositiveSmallIntegerField(choices=EmissionFactor.Scope.choices)
    unit = models.CharField(max_length=30)
    factor_value = models.DecimalField(max_digits=16, decimal_places=8)
    factor_source = models.CharField(max_length=240)
    factor_year = models.PositiveSmallIntegerField()
    is_demo = models.BooleanField(default=False)
    kg_co2e = models.DecimalField(max_digits=20, decimal_places=2)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["organisation", "date", "scope"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="activity_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(kg_co2e__gte=0), name="emissions_nonnegative"
            ),
        ]

    def __str__(self):
        return self.description


class ImportLog(models.Model):
    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    organisation = models.ForeignKey("accounts.Organisation", on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    original_name = models.CharField(max_length=255)
    stored_file = models.FileField(upload_to="private/emissions-imports/", blank=True)
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    row_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    error_messages = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.original_name}: {self.outcome}"
