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


@pytest.fixture
def activity_setup(organisation):
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
    department = Department.objects.create(organisation=organisation, name="Engineering")
    return site, factor, department


def test_activity_department_assignment_and_protected_delete(api_for, admin_user, activity_setup):
    site, factor, department = activity_setup
    client = api_for(admin_user)
    response = client.post(
        "/api/emissions/activities/",
        {
            "description": "Department demo",
            "date": "2026-01-01",
            "quantity": "100",
            "unit": "kWh",
            "site": site.pk,
            "factor": factor.pk,
            "department": department.pk,
        },
    )
    assert response.status_code == 201, response.data
    url = f"/api/emissions/activities/{response.json()['id']}/"
    assert client.get(url).json()["department"] == department.pk
    assert client.delete(f"/api/accounts/departments/{department.pk}/").status_code == 400
    other = Department.objects.create(
        organisation=Organisation.objects.create(name="Other"), name="Other"
    )
    assert client.patch(url, {"department": other.pk}).status_code == 400
    assert client.get(url).json()["department"] == department.pk
    assert client.patch(url, {"department": None}, format="json").status_code == 200
    assert client.delete(f"/api/accounts/departments/{department.pk}/").status_code == 204


@pytest.mark.parametrize("name,expected", [("Engineering", 201), ("Foreign", 400)])
def test_csv_department_is_company_scoped(api_for, admin_user, activity_setup, name, expected):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from emissions.models import ActivityRecord

    Department.objects.create(
        organisation=Organisation.objects.create(name="Other"), name="Foreign"
    )
    text = (
        "date,description,site,factor,quantity,unit,department\n2026-01-01,Demo,Office,Demo,100,kWh,"
        + name
    )
    upload = SimpleUploadedFile("demo.csv", text.encode(), content_type="text/csv")
    response = api_for(admin_user).post(
        "/api/emissions/activities/import/", {"file": upload}, format="multipart"
    )
    assert response.status_code == expected, response.data
    if expected == 201:
        assert ActivityRecord.objects.get().department == activity_setup[2]
    else:
        assert not ActivityRecord.objects.exists()
