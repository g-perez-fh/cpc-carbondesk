from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import AuditLog, Organisation, Site
from emissions.csv_import import CsvImporter
from emissions.models import ActivityRecord, EmissionFactor

pytestmark = pytest.mark.django_db

HEADER = "date,description,site,factor,factor_year,quantity,unit"


@pytest.fixture
def factor(organisation):
    return EmissionFactor.objects.create(
        organisation=organisation,
        name="Demo electricity",
        scope=2,
        unit="kWh",
        kg_per_unit=Decimal("0.4"),
        source="Synthetic test factor",
        year=2026,
        is_demo=True,
    )


@pytest.fixture
def site(organisation):
    return Site.objects.create(organisation=organisation, name="Main office")


def csv_upload(rows, header=HEADER):
    content = "\n".join([header, *rows]) + "\n"
    return SimpleUploadedFile("activities.csv", content.encode(), content_type="text/csv")


def post_csv(client, rows, header=HEADER):
    return client.post(
        "/api/emissions/activities/import/",
        {"file": csv_upload(rows, header)},
        format="multipart",
    )


def test_valid_csv_imports_and_calculates(api_for, admin_user, factor, site):
    response = post_csv(
        api_for(admin_user),
        [
            "2026-01-31,January electricity,Main office,Demo electricity,2026,100,kWh",
            "2026-02-01,February electricity,Main office,Demo electricity,2026,2.5125,kWh",
        ],
    )
    assert response.status_code == 201, response.data
    assert response.json()["created"] == 2
    records = ActivityRecord.objects.order_by("date")
    assert [record.kg_co2e for record in records] == [Decimal("40.00"), Decimal("1.01")]
    assert all(record.organisation == admin_user.organisation for record in records)
    assert all(record.created_by == admin_user for record in records)
    assert AuditLog.objects.filter(action="create").count() == 2


def test_trailing_zeros_are_accepted(api_for, admin_user, factor, site):
    response = post_csv(
        api_for(admin_user),
        ["2026-01-31,Electricity,Main office,Demo electricity,2026,100.00000,kWh"],
    )
    assert response.status_code == 201
    assert ActivityRecord.objects.get().quantity == Decimal("100.0000")


def test_import_is_limited_to_5000_rows(api_for, admin_user, factor, site):
    rows = [
        f"2026-01-31,Electricity {index},Main office,Demo electricity,2026,1,kWh"
        for index in range(5001)
    ]
    response = post_csv(api_for(admin_user), rows)
    assert response.status_code == 400
    assert "5000" in response.json()["file"][0]
    assert not ActivityRecord.objects.exists()


def test_error_list_is_capped(api_for, admin_user, factor, site):
    rows = [
        f"not-a-date,Electricity {index},Main office,Demo electricity,2026,1,kWh"
        for index in range(101)
    ]
    response = post_csv(api_for(admin_user), rows)
    assert response.status_code == 400
    messages = response.json()["file"]
    assert len(messages) == 101
    assert "more errors" in messages[-1]


def test_missing_columns_are_reported(api_for, admin_user):
    response = post_csv(
        api_for(admin_user),
        ["2026-01-31,Electricity,Main office,Demo electricity,2026,100"],
        header="date,description,site,factor,factor_year,quantity",
    )
    assert response.status_code == 400
    assert "unit" in response.json()["file"][0]
    assert not ActivityRecord.objects.exists()


def test_malformed_row_reports_line_number_and_writes_nothing(api_for, admin_user, factor, site):
    response = post_csv(
        api_for(admin_user),
        [
            "2026-01-31,Good row,Main office,Demo electricity,2026,100,kWh",
            "not-a-date,Bad row,Main office,Demo electricity,2026,10,kWh",
            "2026-02-01,Another good row,Main office,Demo electricity,2026,10,kWh",
        ],
    )
    assert response.status_code == 400
    assert "Row 3" in response.json()["file"][0]
    assert not ActivityRecord.objects.exists()
    assert not AuditLog.objects.exists()


def test_unknown_site_and_factor_are_reported(api_for, admin_user, factor, site):
    response = post_csv(
        api_for(admin_user),
        ["2026-01-31,Electricity,Unknown site,Unknown factor,2026,100,kWh"],
    )
    assert response.status_code == 400
    message = " ".join(response.json()["file"])
    assert "Row 2" in message
    assert "Site 'Unknown site'" in message
    assert "Factor 'Unknown factor'" in message
    assert not ActivityRecord.objects.exists()


def test_unit_must_match_the_factor(api_for, admin_user, factor, site):
    response = post_csv(
        api_for(admin_user),
        ["2026-01-31,Electricity,Main office,Demo electricity,2026,100,litres"],
    )
    assert response.status_code == 400
    assert "does not match" in response.json()["file"][0]


def test_factor_year_disambiguates_versions(api_for, admin_user, factor, site):
    EmissionFactor.objects.create(
        organisation=factor.organisation,
        name="Demo electricity",
        scope=1,
        unit="kWh",
        kg_per_unit=Decimal("0.5"),
        source="Older synthetic factor",
        year=2025,
    )
    client = api_for(admin_user)
    without_year = post_csv(
        client, ["2026-01-31,Electricity,Main office,Demo electricity,,100,kWh"]
    )
    assert without_year.status_code == 400
    assert "factor_year" in without_year.json()["file"][0]

    with_year = post_csv(
        client, ["2026-01-31,Electricity,Main office,Demo electricity,2025,100,kWh"]
    )
    assert with_year.status_code == 201
    record = ActivityRecord.objects.get()
    assert record.scope == 1
    assert record.kg_co2e == Decimal("50.00")
    assert record.factor_year == 2025


def test_viewer_cannot_import(api_for, viewer_user):
    response = post_csv(
        api_for(viewer_user),
        ["2026-01-31,Electricity,Main office,Demo electricity,2026,100,kWh"],
    )
    assert response.status_code == 403


def test_other_company_names_are_not_visible(api_for, admin_user, factor, site):
    other = Organisation.objects.create(name="Other")
    Site.objects.create(organisation=other, name="Other site")
    EmissionFactor.objects.create(
        organisation=other,
        name="Other factor",
        scope=1,
        unit="kWh",
        kg_per_unit=1,
        source="Other source",
        year=2026,
    )
    response = post_csv(
        api_for(admin_user),
        ["2026-01-31,Electricity,Other site,Other factor,2026,100,kWh"],
    )
    assert response.status_code == 400
    message = " ".join(response.json()["file"])
    assert "Other site" in message
    assert "Other factor" in message


def test_header_is_normalised_and_blank_rows_are_skipped(api_for, admin_user, factor, site):
    response = post_csv(
        api_for(admin_user),
        ["", "2026-01-31,Electricity,Main office,Demo electricity,2026,100,kWh", ""],
        header=" Date , Description , Site , Factor , Factor Year , Quantity , Unit ",
    )
    assert response.status_code == 201
    assert response.json()["created"] == 1


def test_empty_file_is_rejected(api_for, admin_user):
    response = api_for(admin_user).post(
        "/api/emissions/activities/import/",
        {"file": SimpleUploadedFile("empty.csv", b"", content_type="text/csv")},
        format="multipart",
    )
    assert response.status_code == 400
    assert "empty" in response.json()["file"][0].lower()


def test_missing_file_is_rejected(api_for, admin_user):
    response = api_for(admin_user).post("/api/emissions/activities/import/", {}, format="multipart")
    assert response.status_code == 400
    assert "file" in response.json()


def test_non_utf8_file_is_rejected(api_for, admin_user):
    response = api_for(admin_user).post(
        "/api/emissions/activities/import/",
        {"file": SimpleUploadedFile("bad.csv", b"date,description\n\xff", content_type="text/csv")},
        format="multipart",
    )
    assert response.status_code == 400
    assert "UTF-8" in response.json()["file"][0]


@pytest.mark.parametrize(
    "row, expected",
    [
        (
            f"{date.today() + timedelta(days=1)},Future,Main office,Demo electricity,2026,1,kWh",
            "future",
        ),
        ("2026-01-31,Negative,Main office,Demo electricity,2026,-1,kWh", "non-negative"),
        ("2026-01-31,Precision,Main office,Demo electricity,2026,1.00001,kWh", "four decimal"),
    ],
)
def test_invalid_values_are_reported(api_for, admin_user, factor, site, row, expected):
    response = post_csv(api_for(admin_user), [row])
    assert response.status_code == 400
    assert expected in response.json()["file"][0]
    assert not ActivityRecord.objects.exists()


def test_csv_importer_reports_errors_without_django():
    class SiteStub:
        name = "Main office"

    class FactorStub:
        name = "Demo electricity"
        unit = "kWh"
        kg_per_unit = Decimal("0.4")
        year = 2026

    importer = CsvImporter(
        "date,description,site,factor,quantity,unit\n"
        "2026-01-31,Electricity,Main office,Demo electricity,-1,kWh\n",
        sites_by_name={"Main office": [SiteStub()]},
        factors_by_name={"Demo electricity": [FactorStub()]},
        today=date(2026, 11, 6),
    )
    activities, errors = importer.parse()
    assert activities == []
    assert errors[0]["row"] == 2
    assert "non-negative" in errors[0]["message"]
