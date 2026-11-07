import pytest
from rest_framework.test import APIClient

from accounts.models import AuditLog, User

STRONG_PASSWORD = "Sustain-ability-2026"


@pytest.mark.django_db
def test_register_creates_organisation_with_admin_and_token():
    response = APIClient().post(
        "/api/accounts/register/",
        {"organisation_name": "Green Bakery", "username": "maria", "password": STRONG_PASSWORD},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert body["user"]["role"] == "admin"
    assert body["user"]["organisation"]["name"] == "Green Bakery"
    assert AuditLog.objects.filter(action="create", object_type="Organisation").exists()


@pytest.mark.django_db
def test_register_rejects_weak_password_and_duplicate_username(admin_user):
    client = APIClient()
    weak = client.post(
        "/api/accounts/register/",
        {"organisation_name": "X", "username": "new", "password": "123"},
        format="json",
    )
    assert weak.status_code == 400
    assert weak.json()["error"] == "weak_password" and weak.json()["field"] == "password"

    taken = client.post(
        "/api/accounts/register/",
        {"organisation_name": "X", "username": "ALICE", "password": STRONG_PASSWORD},
        format="json",
    )
    assert taken.status_code == 400 and "username" in taken.json()


def test_login_token_works_and_logout_revokes_it(admin_user):
    client = APIClient()
    response = client.post(
        "/api/accounts/login/",
        {"username": "alice", "password": "a-test-password-only"},
        format="json",
    )
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Token {response.json()['token']}")
    assert client.get("/api/accounts/me/").json()["username"] == "alice"

    assert client.post("/api/accounts/logout/").status_code == 204
    assert client.get("/api/accounts/me/").status_code == 401
    assert list(AuditLog.objects.values_list("action", flat=True)) == ["logout", "login"]


@pytest.mark.django_db
def test_login_rejects_wrong_password_and_is_throttled(admin_user, settings):
    client = APIClient()
    payload = {"username": "alice", "password": "wrong"}
    assert client.post("/api/accounts/login/", payload, format="json").status_code == 400
    statuses = [client.post("/api/accounts/login/", payload).status_code for _ in range(12)]
    assert 429 in statuses


def test_inactive_user_cannot_log_in(admin_user):
    admin_user.is_active = False
    admin_user.save()
    response = APIClient().post(
        "/api/accounts/login/", {"username": "alice", "password": "a-test-password-only"}
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_endpoints_require_authentication():
    client = APIClient()
    for url in ["/api/accounts/me/", "/api/accounts/targets/", "/api/assistant/conversations/"]:
        assert client.get(url).status_code == 401


@pytest.mark.django_db
def test_user_without_organisation_is_refused(api_for):
    staff = User.objects.create_user(username="staff", password="a-test-password-only")
    assert api_for(staff).get("/api/accounts/targets/").status_code == 403
