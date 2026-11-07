# CarbonDesk

CarbonDesk is our Compact Programming capstone project at FH Dortmund. We are
building a web platform for small and medium companies to track Scope 1, 2,
and 3 carbon emissions, view their results, and get AI suggestions for reducing
their footprint.

## Planned stack

| Technology | Purpose |
| --- | --- |
| Python | Main language for the backend and frontend. |
| Django | Backend logic, data validation, authentication, permissions, and database models through its ORM. |
| NiceGUI | Web interface with activity forms, CSV uploads, tables, dashboards, and an assistant chat. |
| PostgreSQL | Shared database for organisations, activity records, emission factors, targets, and chat history. |
| Plotly | Interactive emissions charts and trends. |
| OpenAI API | Explanations and reduction suggestions based on company emissions data. |
| Docker Compose | Run the application components and database together. |
| pytest | Automated tests for calculations and application behavior. |

Django handles the business rules and data access; NiceGUI provides the user
interface.

## Who does what

| Team member | Subsystem | Main responsibilities |
| --- | --- | --- |
| Guillermo Pérez Pérez | Emissions Data & Calculation | Activity entry and CSV import, input validation, emission factors, and conversion to kg CO2e. |
| Harib Khalid | Analytics Dashboard & Reporting | Charts, KPIs, filters, target progress, and PDF/CSV reports. |
| Omotunde Sholola Ganiyu | AI Sustainability Assistant | Company-data chat, reduction recommendations, savings estimates, and monthly summaries. |
| Omotunde Sholola Ganiyu | Users, Organisation & Targets | Login and roles, company structure, yearly reduction targets, alerts, and audit history. |

The team coordinates shared data models and interfaces so the subsystems work
together.

## Project structure

```text
backend/
  config/          Django settings and root URLs
  core/            Shared health endpoint
  emissions/       Guillermo: activity records and calculations
  analytics/       Harib: summaries and reports
  assistant/       Omotunde: AI services
  accounts/        Omotunde: users, organisations and targets
frontend/
  pages/           Matching NiceGUI pages for each subsystem
  api.py           Server-side HTTP calls to Django
  layout.py        Shared navigation and page layout
requirements/      Backend and frontend dependencies
compose.yaml       Local Docker setup
compose.dev.yaml   Optional source mounts and automatic reload
```

Each Django subsystem has `models.py`, `services.py`, `views.py`, and `urls.py`.
Keep calculations and business rules in backend services. The frontend calls
Django through HTTP and must not access the database directly. The shared
`GET /api/health/` endpoint is the first working connection between them.

## Run with Python

Use **Python 3.13** and standard `venv`/`pip`. Run commands from the repository
root. No uv installation is required.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
python backend/manage.py migrate
python backend/manage.py runserver
```

On Windows PowerShell, replace the environment creation, activation, and copy
commands with:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Open a second terminal, activate the same environment, and start the frontend:

```bash
python -m frontend.main
```

- Frontend: http://localhost:8080
- Backend health: http://localhost:8000/api/health/
- Django admin: http://localhost:8000/admin/

The Python setup uses SQLite by default. To use an existing PostgreSQL database,
set `DB_ENGINE=postgresql` and the `POSTGRES_*` values in `.env` before migrating.
The frontend reads `BACKEND_URL` from `.env`. Environment variables take priority.

To create a local admin account:

```bash
python backend/manage.py createsuperuser
```

## Run with Docker Compose

Install Docker with the Compose plugin (Docker Desktop includes it). From the
repository root:

```bash
cp .env.example .env
docker compose up --build
```

On Windows use `Copy-Item .env.example .env`. Keep an existing `.env` rather than
copying over your settings. Compose starts PostgreSQL, applies Django migrations,
and starts the backend and frontend. The same browser URLs above apply.
PostgreSQL data and uploaded files use named volumes. The database is only
accessible inside the Compose network.

For automatic reload while editing Python files:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Useful commands:

```bash
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
docker compose logs -f
docker compose down
```

`docker compose down` keeps the data volumes. Adding `--volumes` deletes them.
Stop the Python servers before starting Compose to avoid port conflicts.
These Docker files are for local development and demos: they use Django's
development server and local credentials, not a production deployment.

## Working together

- Add models and business logic in your Django subsystem and UI in the matching
  `frontend/pages/` module. Coordinate changes to shared models and settings.
- After changing models, run `python backend/manage.py makemigrations`, then
  `python backend/manage.py migrate`. Commit the generated migrations.
- Keep dependency changes in the appropriate `requirements/` file and reinstall
  with `python -m pip install -r requirements-dev.txt`.
- Keep secrets in `.env`; it is ignored by Git. Add new configuration names with
  safe example values to `.env.example`.
- Agree authentication and organisation checks before exposing company data.
  The starter health endpoint is public and contains no company data.

Run checks from an activated environment:

```bash
python backend/manage.py check
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## Current status

Implemented: **Users, Organisation & Targets** and the **AI Sustainability
Assistant**. The emissions page now supports factor creation, activity entry,
CSV import, calculation previews, filtered records, and totals. The dashboard at
http://localhost:8080/dashboard shows KPIs, emissions by scope, a monthly trend,
emissions by site, the top sources and target progress, with filters and a CSV
export. PDF reports are still to come.

- Register a company at http://localhost:8080/register; you become its administrator.
- Roles: `admin` manages the organisation, members and targets; `editor` enters
  data; `viewer` has read-only access.
- No OpenAI key is needed. Without `OPENAI_API_KEY` the assistant answers from
  rules; savings estimates are always calculated by the backend, not the model.

### Shared building blocks for every subsystem

- **API style:** Django REST Framework with token authentication. Every endpoint
  requires login by default. The frontend sends the token through `frontend/api.py`
  (`await api.get("emissions/...")`), which raises `ApiError` with a readable message.
- **Company data isolation:** combine `accounts.mixins.OrganisationScopedMixin` with a
  permission from `accounts.permissions` (for example `CanEditDataOrReadOnly`). The
  mixin filters querysets by `organisation`, attaches new records to the user's
  organisation and writes the audit history automatically.
- **Emissions totals:** targets and the assistant read emissions through
  `core/emissions_data.py`. The emissions subsystem provides
  `emissions.services.totals_by_scope(organisation, start, end)`, returning
  `{1: Decimal, 2: Decimal, 3: Decimal}` in kg CO2e from saved activities.
  The date range includes `start` and excludes `end`.

### Main endpoints

| Area | Endpoints under `/api/` |
| --- | --- |
| Authentication | `accounts/register/`, `accounts/login/`, `accounts/logout/`, `accounts/me/` |
| Organisation | `accounts/organisation/`, `accounts/sites/`, `accounts/members/` |
| Targets & alerts | `accounts/targets/`, `accounts/targets/evaluate/`, `accounts/alerts/`, `accounts/audit-log/` |
| Emissions | `emissions/factors/`, `emissions/activities/`, `emissions/activities/import/`, `emissions/preview/`, `emissions/summary/` |
| Analytics | `analytics/dashboard/`, `analytics/export/csv/` (both accept `start`, `end`, `scope`, `site`) |
| Assistant | `assistant/conversations/`, `assistant/conversations/<id>/messages/`, `assistant/recommendations/`, `assistant/summaries/` |

Implemented UML diagrams and the team presentation video link will be added as
development progresses.

## First emissions workflow

1. Apply migrations with `python backend/manage.py migrate` (Compose applies them
   at startup). Register a company or log in with its admin/editor account.
2. An administrator adds a site on the Organisation page.
3. On **Emissions → Emission factors**, add a factor with its name, scope, unit,
   value in kg CO2e per unit, source, and year.
4. Choose **Add activity**, select the site and factor, and enter the date and
   quantity. Preview the calculation, then save it. Alternatively, choose
   **Import CSV** to add many activities from one file.
5. Browse the records, filter by date/scope/site, and open **Details** to inspect
   the inputs used. Admins/editors can choose **Edit activity** or **Delete activity**
   here. Deletion asks for confirmation. Saved totals also feed the assistant and targets.

For a reproducible example, use a separate demo organisation and add a factor
named **Demo electricity**, Scope 2, unit `kWh`, value `0.4`, source **Synthetic
example**, year `2026`. Select **This is a synthetic demo factor**. An activity
of `100 kWh` must preview and save as **40.00 kg CO2e**. These numbers are for
software testing, not an official emissions estimate. Demo records are labelled
on the emissions page but still contribute to company totals, including the
assistant and targets; keep demo activity separate from real company data.

### Endpoint behavior

- `GET/POST /api/emissions/factors/`: list or add company factors. Each new
  source/version can be a separate factor. PATCH/PUT on `factors/<id>/` corrects
  a factor while keeping its unit and scope fixed. Saved activities stay unchanged.
- `POST /api/emissions/factors/<id>/recalculate/`: explicitly apply the current
  factor to all linked company activities, across all dates/sites. Send the latest
  GET factor object as `{"factor": {...}}`; stale confirmations return HTTP 409.
  The operation is atomic and retains before/after activity snapshots in the audit log.
  Admins/editors can update and recalculate; viewers cannot. Factor deletion is not exposed.
- `POST /api/emissions/preview/`: send `factor`, `quantity`, and `unit`; receive
  `kg_co2e` without saving a record. Include an `activity` ID when editing to
  preview its saved factor inputs if the factor selection is unchanged.
- `GET/POST /api/emissions/activities/`: list or create records. Creation accepts
  `description`, `date` (`YYYY-MM-DD`), `factor` ID, `site` ID, `quantity`, and
  `unit`. The backend assigns the company, creator, scope, and result.
- `GET /api/emissions/activities/<id>/`: inspect the saved calculation inputs.
- `PATCH/PUT /api/emissions/activities/<id>/`: correct an activity and recalculate.
  PATCH accepts only changed fields; PUT requires all entry fields. When selecting
  a factor with a different unit, send that unit too.
- `DELETE /api/emissions/activities/<id>/`: remove an activity from totals (HTTP 204).
  Admins/editors may edit/delete; viewers cannot. Before/after edit snapshots and
  deleted record details remain in the existing audit log, atomically with the change.
  Edits keep the saved factor version unless a different factor is selected.
  The creator and creation date remain unchanged. There is no restore button.
- `POST /api/emissions/activities/import/`: upload a CSV file in the `file`
  multipart field. The response reports how many records were created.
- `GET /api/emissions/summary/`: record count, demo count, total and scope totals.

Activity lists and summaries accept `start` (inclusive), `end` (exclusive),
`scope` (1–3), and `site`. Lists use 20 records per page and accept `page`.
Omitted date filters include all dates. Invalid filters return HTTP 400.
Admins/editors can add factors, add activities, and import CSV; viewers can read
and preview. All endpoints require an organisation membership. Cross-company IDs
are rejected.

Quantities must be non-negative and have at most four decimal places; factors
allow eight. Zero is valid. Units must match exactly: conversions are not implicit.
Activity dates cannot be in the future. The calculation uses `Decimal` and rounds
half up to **0.01 kg CO2e** once per record; totals sum those saved results.
Records preserve the factor name, scope, value, unit, source, year, and demo flag
used in the latest calculation. Recalculation replaces these snapshots while
retaining the previous values in the audit log. Writes use the existing audit log.

### CSV import

The **Import CSV** button accepts UTF-8 files with a header row. Required columns
are `date`, `description`, `site`, `factor`, `quantity`, and `unit`. The optional
`factor_year` column selects one version when several factors share a name. Dates
use `YYYY-MM-DD`; site and factor names must match the company exactly.

Validation is all-or-nothing: if any row fails, no records are saved and the
response lists each problem with its physical line number (up to 100 problems
are shown). Imports are limited to 5 MB and 5,000 data rows. Each imported record is calculated with the same
rules as manual entry and receives its own audit-log entry. The import does not
check for duplicate activities, so re-uploading a file creates the rows again.
A template is available from the import dialog.

Department links and the local streaming pipeline are available below.
PostgreSQL/SQLite remain the default setup; Hometask 3 has a separate MySQL stack.

### Correcting a factor

On **Emissions → Emission factors**, select **Edit factor** and save the correction.
New activities use the corrected value; existing activities keep their saved inputs.
Choose **Recalculate activities** and confirm to update all linked records and totals.
Use a new factor for a different unit, scope, or a separate publication/version.
Editing an existing activity with its original factor continues to use its saved
calculation inputs until explicit recalculation. Its preview follows the same rule.

### Departments

Administrators can manage departments on the Organisation page. Activities have
an optional company department. CSV files accept an optional `department` column
matching the department name exactly. Existing activities remain unassigned.
Referenced departments cannot be deleted; viewers and editors cannot manage them.

### Local telemetry pipeline

`backend/emissions/streaming.py` provides `ActivityStream`, `ScopeFilter`,
`EmissionTransformer`, and composable `Pipeline` classes for Homework 2.
Compose `ScopeFilter([2]) + EmissionTransformer(factors)` and iterate over
`pipeline.run(ActivityStream(events))`. Events contain `scope`, `factor`,
`quantity`, and `unit`. The factor mapping contains `scope`, `kg_per_unit`, and
`unit` for each factor name. Results add `tonnes_co2e` as a Decimal. Invalid events
raise `EmissionsError`. This is a local pipeline, with no broker or persistence.

### Optional database backups

`docker compose -f compose.yaml -f compose.backup.yaml up -d --build` enables
PostgreSQL backups at startup and every 24 hours while the backup container runs.
Dumps go into the `backups` named volume. Check container logs for errors.
Backups cover the database, not uploads. There is no retention policy or off-site
copy. Restore a dump with `pg_restore` into a separate empty database to validate
recovery before relying on this workflow.

## Homework recording setup

Guillermo's three explicit OOP classes are `CO2eCalculator`, `CsvImporter`, and
`ScopeFilter`. Each initializes its state in a constructor and provides validating
setters and getters. The scope filter is also reused in the streaming assignment.
Run the synthetic OOP and streaming demonstration from the repository root:

```bash
PYTHONPATH=backend python examples/homework_demo.py
```

### MySQL for Hometask 3

The separate homework stack leaves the default PostgreSQL setup unchanged:

```bash
docker compose -f compose.mysql.yaml up -d --build
docker compose -f compose.mysql.yaml logs backend
```

Stop other servers on ports 8000 and 8080 first. Open http://localhost:8080,
register a demo company, add a site and synthetic factor, and save an activity.
Inspect persistence using the database client (enter the local homework password
from `compose.mysql.yaml` at the prompt):

```bash
docker compose -f compose.mysql.yaml exec db mysql -u carbondesk -p carbondesk
```

```sql
SELECT id, description, quantity, kg_co2e FROM emissions_activityrecord;
```

This uses MySQL 8.4 and Django's MySQL backend with mysqlclient. The driver is an
optional dependency in `requirements/mysql.txt`; the homework Dockerfile installs
its native build prerequisites. Local credentials are for this isolated demo only.
`docker compose -f compose.mysql.yaml down` preserves the MySQL data volume.

### Submission checklist

Team names and subsystem ownership are listed under **Who does what** above.
For each assignment branch, add the rendered LaTeX class diagrams and the direct
unified team-video link. Those artifacts are intentionally excluded from the
current implementation commits. The video link is pending recording/upload;
no placeholder URL represents a completed submission. Each teammate must supply
their own implemented class explanation and subsystem error-handling evidence.
Hometasks 1 and 2 use the user-specified branches `Homeassignment1` and
`HomeworkAssignment2`. Confirm naming for 3 and 4 against the course submission
instructions before pushing. No submission branches or videos are published here.
