"""Tests for the company-scoped import history endpoint (dev row A06).

`GET /api/emissions/imports/` returns the organisation's persisted import
attempts in latest-first order, without storage paths (import contract,
history section). These tests cover authentication, organisation isolation,
ordering and response shape, the empty case, and one visible attempt per
outcome. Upload storage is isolated by the shared autouse fixture in
``backend/conftest.py`` (row A05), so the HTTP imports here never touch the
real ``backend/media``, and no test here adds its own storage override.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from accounts.models import User
from emissions.models import ActivityRecord, EmissionFactor, ImportLog

pytestmark = pytest.mark.django_db

HISTORY_URL = "/api/emissions/imports/"

HEADER = "date,description,site,factor,quantity,unit"

HISTORY_RESPONSE_FIELDS = {
    "id",
    "original_name",
    "outcome",
    "row_count",
    "accepted_count",
    "rejected_count",
    "created_count",
    "error_messages",
    "created_at",
}


@pytest.fixture
def rival_org_admin(make_member):
    """A second company with its own admin user, for isolation checks."""
    from accounts.models import Organisation

    other = Organisation.objects.create(name="Rival GmbH")
    return other, make_member("rival", User.Role.ADMIN, org=other)


@pytest.fixture
def demo_factor_site(organisation):
    from accounts.models import Site

    site = Site.objects.create(organisation=organisation, name="Office")
    factor = EmissionFactor.objects.create(
        organisation=organisation,
        name="Demo",
        scope=2,
        unit="kWh",
        kg_per_unit="0.4",
        source="Synthetic",
        year=2026,
        is_demo=True,
    )
    return site, factor


def make_log(user, *, name, outcome):
    """Create one history row directly in the user's organisation."""
    return ImportLog.objects.create(
        organisation=user.organisation, created_by=user, original_name=name, outcome=outcome
    )


def post_import(api_for, user, file_name, text):
    upload = SimpleUploadedFile(file_name, text.encode(), content_type="text/csv")
    return api_for(user).post(
        "/api/emissions/activities/import/", {"file": upload}, format="multipart"
    )


def test_unauthenticated_history_is_rejected():
    response = APIClient().get(HISTORY_URL)
    assert response.status_code == 401


def test_history_is_organisation_scoped(api_for, admin_user, rival_org_admin):
    other, rival_admin = rival_org_admin
    my_first = make_log(admin_user, name="mine-1.csv", outcome="success")
    my_second = make_log(admin_user, name="mine-2.csv", outcome="rejected")
    rival_first = make_log(rival_admin, name="rival-1.csv", outcome="success")
    rival_second = make_log(rival_admin, name="rival-2.csv", outcome="failed")

    items = api_for(admin_user).get(HISTORY_URL).json()

    assert {item["original_name"] for item in items} == {"mine-1.csv", "mine-2.csv"}
    assert len(items) == 2
    assert {item["id"] for item in items} == {my_first.pk, my_second.pk}

    rival_items = api_for(rival_admin).get(HISTORY_URL).json()
    assert {item["original_name"] for item in rival_items} == {"rival-1.csv", "rival-2.csv"}
    assert {item["id"] for item in rival_items} == {rival_first.pk, rival_second.pk}


def test_history_is_latest_first_with_documented_fields(api_for, admin_user):
    first = make_log(admin_user, name="oldest.csv", outcome="success")
    second = make_log(admin_user, name="middle.csv", outcome="rejected")
    third = make_log(admin_user, name="newest.csv", outcome="failed")

    response = api_for(admin_user).get(HISTORY_URL)
    assert response.status_code == 200
    items = response.json()

    # ids ascend with creation, so descending ids prove latest-first order.
    assert [item["id"] for item in items] == [third.pk, second.pk, first.pk]
    for item in items:
        assert set(item) == HISTORY_RESPONSE_FIELDS
        assert "stored_file" not in item
        assert isinstance(item["error_messages"], list)
        assert item["created_at"]


def test_empty_history_returns_empty_list(api_for, admin_user):
    response = api_for(admin_user).get(HISTORY_URL)
    assert response.status_code == 200
    assert response.json() == []


def test_success_rejected_and_failed_outcomes_appear(api_for, admin_user, demo_factor_site):
    valid = post_import(
        api_for,
        admin_user,
        "valid.csv",
        "date,description,site,factor,quantity,unit\n"
        "2026-01-01,January,Office,Demo,100,kWh\n"
        "2026-02-01,February,Office,Demo,50,kWh\n",
    )
    assert valid.status_code == 201, valid.data
    rejected_response = post_import(
        api_for,
        admin_user,
        "rejected.csv",
        "date,description,site,factor,quantity,unit\n2026-01-01,Demo row,Office,Demo,100,tonnes\n",
    )
    assert rejected_response.status_code == 400, rejected_response.data
    crashed = make_log(admin_user, name="crashed.csv", outcome=ImportLog.Outcome.FAILED)

    items = api_for(admin_user).get(HISTORY_URL).json()

    assert {item["outcome"] for item in items} == {"success", "rejected", "failed"}
    success = next(item for item in items if item["outcome"] == "success")
    rejected = next(item for item in items if item["outcome"] == "rejected")
    failed = next(item for item in items if item["outcome"] == "failed")

    assert success["created_count"] == 2
    assert success["accepted_count"] == 2
    assert success["rejected_count"] == 0

    # One rejected row despite two validation messages, and nothing created
    # for a rejected batch (import contract, counting rules).
    assert rejected["row_count"] == 1
    assert rejected["rejected_count"] == 1
    assert rejected["created_count"] == 0

    assert failed["original_name"] == "crashed.csv"
    assert failed["id"] == crashed.pk


def test_header_only_file_is_rejected_with_its_own_counters(api_for, admin_user, demo_factor_site):
    """A header-only upload counts as one rejected row (csv_import labels
    file-level messages row 1) and creates nothing (import contract)."""
    header_only = SimpleUploadedFile(
        "empty.csv",
        (HEADER + "\n").encode(),
        content_type="text/csv",
    )
    response = api_for(admin_user).post(
        "/api/emissions/activities/import/", {"file": header_only}, format="multipart"
    )

    assert response.status_code == 400, response.data
    log = ImportLog.objects.get()
    assert log.outcome == ImportLog.Outcome.REJECTED
    assert log.row_count == 1
    assert log.rejected_count == 1
    assert log.accepted_count == 0
    assert log.created_count == 0
    assert log.error_messages == ["Row 1: The file has no activity rows."]
    assert ActivityRecord.objects.count() == 0
