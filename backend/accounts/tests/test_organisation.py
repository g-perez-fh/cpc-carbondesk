import pytest

from accounts.models import AuditLog, Organisation, Site, User

pytestmark = pytest.mark.django_db


def test_members_only_see_their_own_organisation(api_for, admin_user, make_member):
    other_org = Organisation.objects.create(name="Rival AG")
    Site.objects.create(organisation=other_org, name="Rival plant")
    make_member("eve", User.Role.ADMIN, org=other_org)
    client = api_for(admin_user)

    assert client.get("/api/accounts/sites/").json() == []
    usernames = [m["username"] for m in client.get("/api/accounts/members/").json()]
    assert usernames == ["alice"]
    rival_site = Site.objects.get(name="Rival plant")
    assert client.delete(f"/api/accounts/sites/{rival_site.pk}/").status_code == 404


def test_admin_manages_sites_and_changes_are_audited(api_for, admin_user):
    client = api_for(admin_user)
    created = client.post("/api/accounts/sites/", {"name": "HQ", "location": "Dortmund"})
    assert created.status_code == 201
    site_id = created.json()["id"]

    duplicate = client.post("/api/accounts/sites/", {"name": "hq"})
    assert duplicate.status_code == 400

    client.patch(f"/api/accounts/sites/{site_id}/", {"location": "Bochum"})
    client.delete(f"/api/accounts/sites/{site_id}/")

    log = client.get("/api/accounts/audit-log/").json()["results"]
    assert [entry["action"] for entry in log] == ["delete", "update", "create"]
    assert log[1]["changes"] == {"location": {"from": "Dortmund", "to": "Bochum"}}
    assert log[0]["actor"] == "alice"


def test_viewer_has_read_only_access(api_for, viewer_user):
    client = api_for(viewer_user)
    assert client.get("/api/accounts/organisation/").status_code == 200
    assert client.patch("/api/accounts/organisation/", {"name": "Hacked"}).status_code == 403
    assert client.post("/api/accounts/sites/", {"name": "Shed"}).status_code == 403
    assert client.get("/api/accounts/audit-log/").status_code == 403


def test_admin_updates_organisation(api_for, admin_user):
    response = api_for(admin_user).patch(
        "/api/accounts/organisation/", {"employee_count": 42}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["employee_count"] == 42
    assert AuditLog.objects.filter(action="update", object_type="Organisation").exists()


def test_admin_creates_member_in_own_organisation(api_for, admin_user, organisation):
    response = api_for(admin_user).post(
        "/api/accounts/members/",
        {"username": "eddie", "password": "Carbon-neutral-2030", "role": "editor"},
    )
    assert response.status_code == 201
    assert "password" not in response.json()
    member = User.objects.get(username="eddie")
    assert member.organisation == organisation and member.can_edit_data
    assert member.check_password("Carbon-neutral-2030")


def test_member_password_is_validated(api_for, admin_user):
    response = api_for(admin_user).post(
        "/api/accounts/members/", {"username": "eddie", "password": "password"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "weak_password"


def test_deleting_member_deactivates_instead(api_for, admin_user, viewer_user):
    response = api_for(admin_user).delete(f"/api/accounts/members/{viewer_user.pk}/")
    assert response.status_code == 204
    viewer_user.refresh_from_db()
    assert viewer_user.is_active is False


def test_last_admin_cannot_be_demoted_or_deactivated(api_for, admin_user):
    client = api_for(admin_user)
    url = f"/api/accounts/members/{admin_user.pk}/"
    for response in (client.patch(url, {"role": "viewer"}), client.delete(url)):
        assert response.status_code == 409
        assert response.json()["error"] == "last_admin"
    admin_user.refresh_from_db()
    assert admin_user.role == "admin" and admin_user.is_active


def test_admin_can_step_down_when_another_admin_exists(api_for, admin_user, make_member):
    make_member("bob", User.Role.ADMIN)
    response = api_for(admin_user).patch(
        f"/api/accounts/members/{admin_user.pk}/", {"role": "editor"}
    )
    assert response.status_code == 200
