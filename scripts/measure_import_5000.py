"""Stage-5 (plan.md line 270) import-performance measurement — runs manually, NOT on CI.

Measures the real web import flow (multipart POST to the import endpoint,
including storage write, parsing, all-or-nothing save and the per-record audit
entries) against a disposable SQLite database and a throwaway media directory.
It is deliberately not a pytest test: wall-clock timing targets are
nondeterministic, so the numbers live in this script's output and in the row
report, not in the test suite.

Usage (from the repository root, in an activated venv):

    .venv/bin/python scripts/measure_import_5000.py

Data is synthetic demo data throughout (description prefix "Demo import row",
``is_demo=True`` factor). Timing depends on the machine (including the shared
network mount speed of the workspace), so treat the output as one setup's
evidence, not a general guarantee.
"""

import pathlib
import sys
import tempfile
import time
import types
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import django  # noqa: E402
from django.conf import settings  # noqa: E402

URLCONF = types.ModuleType("measure_urlconf")
URLCONF.urlpatterns = None  # filled in after settings.configure
sys.modules["measure_urlconf"] = URLCONF

if not settings.configured:
    sink = pathlib.Path(tempfile.mkdtemp(prefix="carbondesk-measure-"))
    settings.configure(
        DEBUG=False,
        SECRET_KEY="measurement-only-not-a-secret",
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "rest_framework",
            "core",
            "accounts",
            "emissions",
        ],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": sink / "measured.sqlite3",
            }
        },
        MEDIA_ROOT=sink / "media",
        ROOT_URLCONF="measure_urlconf",
        AUTH_USER_MODEL="accounts.User",
        AUTH_PASSWORD_VALIDATORS=[],
        USE_TZ=True,
    )
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.urls import include, path  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from accounts.models import AuditLog, Organisation, Site, User  # noqa: E402
from emissions.models import ActivityRecord, EmissionFactor, ImportLog  # noqa: E402

URLCONF.urlpatterns = [path("api/emissions/", include("emissions.urls"))]

HEADER = "date,description,site,factor,quantity,unit"
ROWS = 5000
FIRST_DAY = date(2026, 1, 1)


def csv_bytes(broken_every_third=False):
    lines = [HEADER]
    for i in range(ROWS):
        day = FIRST_DAY + timedelta(days=i // 200)  # ~20 sheets of 200 rows per day
        quantity = 100 if i % 2 == 0 else 50
        unit = "W" if (broken_every_third and i % 3 == 2) else "kWh"
        lines.append(f"{day.isoformat()},Demo import row {i},Office,Demo,{quantity},{unit}")
    return ("\n".join(lines) + "\n").encode()


def setup_fixtures():
    organisation = Organisation.objects.create(name="Measurement Demo GmbH")
    User.objects.create_user(
        username="measurer",
        password="measurement-only",
        organisation=organisation,
        role=User.Role.ADMIN,
    )
    Site.objects.create(organisation=organisation, name="Office")
    EmissionFactor.objects.create(
        organisation=organisation,
        name="Demo",
        scope=2,
        unit="kWh",
        kg_per_unit=Decimal("0.4"),
        source="Synthetic measurement example",
        year=2026,
        is_demo=True,
    )
    return organisation


def measure(label, content, repetitions=2):
    client = APIClient()
    client.force_authenticate(User.objects.get(username="measurer"))
    for attempt in range(1, repetitions + 1):
        activity_count = ActivityRecord.objects.count()
        started = time.perf_counter()
        response = client.post(
            "/api/emissions/activities/import/",
            {"file": SimpleUploadedFile("demo-import-5000.csv", content, content_type="text/csv")},
            format="multipart",
        )
        elapsed = time.perf_counter() - started
        log = ImportLog.objects.order_by("-id").first()
        print(
            f"{label} run {attempt}: {elapsed:.2f} s | HTTP {response.status_code} | "
            f"created {ActivityRecord.objects.count() - activity_count} | "
            f"log outcome={log.outcome} rows={log.row_count} rejected={log.rejected_count} | "
            f"messages={len(log.error_messages)}"
        )
        del response
    audits = AuditLog.objects.count()
    print(f"{label}: total audit rows now {audits}")


if __name__ == "__main__":
    call_command("migrate", verbosity=0, interactive=False)
    organisation = setup_fixtures()

    print(f"Disposal DB: {settings.DATABASES['default']['NAME']}")
    print(f"Target: {ROWS} data rows in under 10 s (plan.md Stage 5 target)")
    print()
    measure("valid-5000", csv_bytes())
    print()
    measure("error-heavy (every 3rd row invalid)", csv_bytes(broken_every_third=True))
