from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import Organisation, User


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()


@pytest.fixture(autouse=True)
def no_gemini_key(settings, monkeypatch):
    """Tests never call the real AI service unless they opt in by mocking it.

    Clearing the key keeps a developer's ``.env`` from triggering live model
    traffic. As a second guard, the adapter's HTTP entry point fails loudly
    instead of reaching the network when a test forgets to mock it.
    """

    def forbid_live_request(*args, **kwargs):
        raise AssertionError("Assistant tests must mock assistant.llm.httpx.post.")

    settings.GEMINI_API_KEY = ""
    monkeypatch.setattr("assistant.llm.httpx.post", forbid_live_request)


@pytest.fixture(autouse=True)
def isolated_media_root(settings, tmp_path, monkeypatch):
    """Redirect upload storage to a temporary directory for every backend test.

    ``MEDIA_ROOT`` and the default storage object that ``emissions.services``
    imported are re-pointed at a throwaway location, so no test anywhere can
    write files into the real ``backend/media`` tree. Returns the temporary
    media directory for assertions on stored files.
    """
    from django.core.files.storage import FileSystemStorage

    media_dir = tmp_path / "media"
    settings.MEDIA_ROOT = media_dir
    storage = FileSystemStorage(location=str(media_dir))
    monkeypatch.setattr("django.core.files.storage.default_storage", storage)
    monkeypatch.setattr("emissions.services.default_storage", storage)
    return media_dir


@pytest.fixture
def organisation(db):
    return Organisation.objects.create(name="Acme GmbH", industry="Manufacturing")


@pytest.fixture
def make_member(organisation):
    def make(username, role=User.Role.VIEWER, org=None):
        return User.objects.create_user(
            username=username,
            password="a-test-password-only",
            organisation=org or organisation,
            role=role,
        )

    return make


@pytest.fixture
def admin_user(make_member):
    return make_member("alice", User.Role.ADMIN)


@pytest.fixture
def viewer_user(make_member):
    return make_member("victor", User.Role.VIEWER)


@pytest.fixture
def api_for():
    def client_for(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return client_for


@pytest.fixture
def emissions(monkeypatch):
    """Stand in for the emissions subsystem: set kg CO2e per scope for any period."""
    values = {1: Decimal("0"), 2: Decimal("0"), 3: Decimal("0")}

    def totals_by_scope(organisation, start, end):
        return dict(values)

    monkeypatch.setattr("emissions.services.totals_by_scope", totals_by_scope, raising=False)
    return values
