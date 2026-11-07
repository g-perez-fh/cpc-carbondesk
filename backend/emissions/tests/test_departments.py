import pytest

from accounts.models import Department, Organisation

pytestmark = pytest.mark.django_db


def test_department_admin_management(api_for, admin_user, viewer_user):
    client = api_for(admin_user)
    response = client.post("/api/accounts/departments/", {"name": "Engineering"})
    assert response.status_code == 201
    pk = response.json()["id"]
    assert api_for(viewer_user).get("/api/accounts/departments/").status_code == 200
    assert api_for(viewer_user).delete(f"/api/accounts/departments/{pk}/").status_code == 403
    assert client.delete(f"/api/accounts/departments/{pk}/").status_code == 204


def test_other_company_departments_hidden(api_for, admin_user):
    org = Organisation.objects.create(name="Other")
    department = Department.objects.create(organisation=org, name="Finance")
    client = api_for(admin_user)
    assert client.get("/api/accounts/departments/").json() == []
    assert (
        client.patch(f"/api/accounts/departments/{department.pk}/", {"name": "Changed"}).status_code
        == 404
    )
