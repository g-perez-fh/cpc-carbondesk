"""Accounts exceptions: the classes themselves, and how services and views use them."""

import pytest
from django.db.models.deletion import ProtectedError

from accounts import services
from accounts.exceptions import (
    AccountsError,
    InvalidTargetError,
    LastAdminError,
    SiteInUseError,
    WeakPasswordError,
)
from accounts.models import AuditLog, ReductionTarget, Site, User

# The classes (no database) ----------------------------------------------------------


def test_base_error_uses_default_or_custom_message():
    assert AccountsError().message == "The request could not be completed."
    error = AccountsError("custom")
    assert str(error) == "custom" and error.status_code == 400


@pytest.mark.parametrize(
    "cls, status, code",
    [
        (LastAdminError, 409, "last_admin"),
        (WeakPasswordError, 400, "weak_password"),
        (SiteInUseError, 400, "site_in_use"),
        (InvalidTargetError, 400, "invalid_target"),
    ],
)
def test_subclasses_carry_status_and_code(cls, status, code):
    error = cls()
    assert isinstance(error, AccountsError)
    assert error.status_code == status
    assert error.as_response_data()["error"] == code
    assert error.as_response_data()["detail"] == cls.default_message


def test_field_is_only_included_when_set():
    assert WeakPasswordError("short").as_response_data() == {
        "error": "weak_password",
        "detail": "short",
        "field": "password",
    }
    assert "field" not in LastAdminError().as_response_data()


# Services ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_register_raises_weak_password_with_validator_messages():
    with pytest.raises(WeakPasswordError) as error:
        services.register_organisation(organisation_name="X", username="new", password="123")
    assert "too short" in error.value.message
    assert not User.objects.filter(username="new").exists()


def test_ensure_admin_remains_raises_for_last_admin(admin_user):
    with pytest.raises(LastAdminError):
        services.ensure_admin_remains(admin_user, role="viewer")
    with pytest.raises(LastAdminError):
        services.ensure_admin_remains(admin_user, is_active=False)
    services.ensure_admin_remains(admin_user, role="admin")  # no change, no error


def test_delete_site_in_use_raises_and_keeps_no_audit_entry(admin_user, organisation, monkeypatch):
    site = Site.objects.create(organisation=organisation, name="HQ")

    def protected_delete(*args, **kwargs):
        raise ProtectedError("in use", set())

    monkeypatch.setattr(Site, "delete", protected_delete)
    with pytest.raises(SiteInUseError):
        services.delete_site(site, actor=admin_user)
    assert not AuditLog.objects.filter(action="delete").exists()


def test_delete_site_records_audit_entry(admin_user, organisation):
    site = Site.objects.create(organisation=organisation, name="HQ")
    services.delete_site(site, actor=admin_user)
    assert not Site.objects.exists()
    assert AuditLog.objects.get(action="delete").object_repr == "HQ"


# Views ------------------------------------------------------------------------------


def test_view_returns_json_error_for_accounts_error(api_for, admin_user):
    response = api_for(admin_user).delete(f"/api/accounts/members/{admin_user.pk}/")
    assert response.status_code == 409
    assert response.json() == LastAdminError().as_response_data()


@pytest.mark.django_db
def test_register_view_returns_weak_password_error():
    from rest_framework.test import APIClient

    response = APIClient().post(
        "/api/accounts/register/",
        {"organisation_name": "X", "username": "new", "password": "password"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "weak_password"
    assert "too common" in response.json()["detail"]


def test_check_target_rejects_backwards_years_and_duplicates(organisation):
    with pytest.raises(InvalidTargetError, match="after the baseline"):
        services.check_target(organisation, scope="all", baseline_year=2030, target_year=2025)
    existing = ReductionTarget.objects.create(
        organisation=organisation,
        baseline_year=2024,
        baseline_kg_co2e=1000,
        target_year=2030,
        reduction_percent=40,
    )
    with pytest.raises(InvalidTargetError, match="already exists"):
        services.check_target(organisation, scope="all", baseline_year=2024, target_year=2030)
    # Editing the existing target itself is not a duplicate.
    services.check_target(
        organisation, scope="all", baseline_year=2024, target_year=2030, exclude=existing
    )


def test_target_view_returns_invalid_target_json(api_for, admin_user):
    payload = {
        "baseline_year": 2030,
        "baseline_kg_co2e": "1000",
        "target_year": 2025,
        "reduction_percent": "40",
    }
    response = api_for(admin_user).post("/api/accounts/targets/", payload)
    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_target",
        "detail": "The target year must be after the baseline year.",
        "field": "target_year",
    }
