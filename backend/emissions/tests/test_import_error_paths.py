"""Regression tests for the import endpoint failure paths (dev row A02).

Pins the documented HTTP behavior for expected storage/database failures and
proves that a programming error inside the import flow is no longer hidden by
the endpoint. Row-count semantics, file retention policy and transaction design
are deliberately not verified here; later rows own those.

Upload storage is shared test infrastructure since row A05: the autouse
``isolated_media_root`` fixture in ``backend/conftest.py`` redirects the
default storage to a temporary directory for every test, so no import in any
test file can reach the real ``backend/media`` location. This file keeps a
thin ``isolated_storage`` alias so tests can assert on the temporary media
directory, and patches a failing storage only where a storage failure is the
subject under test.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from emissions.models import ActivityRecord, ImportLog

pytestmark = pytest.mark.django_db

HEADER = "date,description,site,factor,quantity,unit"
VALID_ROWS = ["2026-01-01,Demo,Office,Demo,100,kWh"]


@pytest.fixture(autouse=True)
def isolated_storage(isolated_media_root):
    """Alias of the shared fixture, for tests that assert on file locations."""
    return isolated_media_root


@pytest.fixture
def demo_factor_site(organisation):
    from accounts.models import Site
    from emissions.models import EmissionFactor

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


def demo_upload():
    text = "\n".join([HEADER, *VALID_ROWS]) + "\n"
    # The client's file name must not influence the stored file path.
    return SimpleUploadedFile("company-realname.csv", text.encode(), content_type="text/csv")


def post_import(api_for, user):
    return api_for(user).post(
        "/api/emissions/activities/import/", {"file": demo_upload()}, format="multipart"
    )


def test_success_stores_file_with_generated_name(
    api_for, admin_user, demo_factor_site, isolated_storage
):
    response = post_import(api_for, admin_user)
    assert response.status_code == 201, response.data
    log = ImportLog.objects.get()
    assert log.outcome == ImportLog.Outcome.SUCCESS
    stored_name = log.stored_file.name
    assert stored_name.startswith(f"private/emissions-imports/{admin_user.organisation_id}/")
    assert stored_name.endswith(".csv")
    assert "company-realname" not in stored_name
    assert (isolated_storage / stored_name).exists()


def test_programming_errors_are_not_swallowed(monkeypatch, api_for, admin_user):
    def broken_persist_import(*args, **kwargs):
        raise RuntimeError("Simulated programming error, e.g. an undefined name.")

    monkeypatch.setattr("emissions.views.persist_import", broken_persist_import)
    with pytest.raises(RuntimeError):
        post_import(api_for, admin_user)
    assert ActivityRecord.objects.count() == 0
    assert ImportLog.objects.count() == 0


def test_storage_failure_returns_documented_response_and_logs_attempt(
    api_for, admin_user, monkeypatch, isolated_storage
):
    from django.core.files.storage import FileSystemStorage

    class FailingStorage(FileSystemStorage):
        def save(self, name, content, max_length=None):
            raise OSError("Simulated storage failure.")

    monkeypatch.setattr(
        "emissions.services.default_storage",
        FailingStorage(location=str(isolated_storage)),
    )
    response = post_import(api_for, admin_user)
    assert response.status_code == 500
    assert response.data == {"file": ["The import could not be saved. No activities were created."]}
    log = ImportLog.objects.get()
    assert log.outcome == ImportLog.Outcome.FAILED
    # The log records a sanitized message, never the raw OSError text.
    assert log.error_messages == [
        "Upload storage failed: an internal error occurred while saving the file."
    ]
    assert ActivityRecord.objects.count() == 0


def test_database_failure_deletes_file_and_records_failed_attempt(
    api_for, admin_user, monkeypatch, isolated_storage
):
    from django.db import DatabaseError

    def fail_saving_activities(*args, **kwargs):
        raise DatabaseError("Simulated database failure.")

    monkeypatch.setattr("emissions.services.import_activities", fail_saving_activities)
    response = post_import(api_for, admin_user)
    assert response.status_code == 500
    assert response.data == {"file": ["The import could not be saved. No activities were created."]}
    log = ImportLog.objects.get()
    assert log.outcome == ImportLog.Outcome.FAILED
    # The log records a sanitized message, never the raw DatabaseError text.
    assert log.error_messages == [
        "Database save failed: an internal error occurred while saving activities."
    ]
    assert not log.stored_file  # stored upload was deleted
    leftovers = [path for path in isolated_storage.rglob("*") if path.is_file()]
    assert leftovers == []
    assert ActivityRecord.objects.count() == 0
