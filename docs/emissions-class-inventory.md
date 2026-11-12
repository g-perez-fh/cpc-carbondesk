# Emissions class inventory — source for the subsystem class diagram

Status: **inventory of the implemented code**, written 11 November 2026 as delivery
task D01 of `docs/emissions-delivery-plan.md`. It lists the actual classes, their
key fields and public methods, and the relationships between them, with code
references, so the D04 worker can derive `docs/diagrams/emissions-classes.mmd`
from this file without re-reading every module. Everything here describes
current code; nothing is proposed. Line numbers refer to the working tree on
branch `feature/emissions-import-history` (factor-seed commit `4aa24d7`,
11 November 2026) and may shift if the code changes.

`backend/emissions/` mixes four kinds of things: Django models, plain Python
classes (calculator, importer, dataclass, exception), **module-level service
functions** (there is deliberately no `Service` class), and Django/DRF HTTP
infrastructure (views, serializers). Only the first two groups belong on the
class diagram; sections 5–6 list the rest so the inventory is complete.

## 1. Domain models — `backend/emissions/models.py`

All three models are plain `models.Model` subclasses with **no domain methods
beyond `__str__`**; behaviour lives in the module functions of section 3. That
is a deliberate difference from the proposal's draft diagram (slide 2), which
sketched `calc_co2e()` on `ActivityRecord` and `update_value()` on
`EmissionFactor`.

### `EmissionFactor` (models.py:10)

One company's emission factor for one category/year. Nested `Scope`
`IntegerChoices` with `DIRECT = 1`, `ENERGY = 2`, `INDIRECT = 3`
(models.py:11–14).

| Field | Type / constraint | Reference |
| --- | --- | --- |
| `organisation` | FK → `accounts.Organisation`, required, `CASCADE` | models.py:16 |
| `name` | CharField(100) | models.py:17 |
| `scope` | PositiveSmallIntegerField, choices 1–3 | models.py:18 |
| `unit` | CharField(30) | models.py:19 |
| `kg_per_unit` | DecimalField(16, 8), validator ≥ 0 | models.py:20–22 |
| `source` | CharField(240) | models.py:23 |
| `year` | PositiveSmallIntegerField, 1–9999 | models.py:24–26 |
| `is_demo` | BooleanField, default `False` | models.py:27 |
| `created_at` | DateTimeField, `auto_now_add` | models.py:28 |

Meta: ordering `["name", "-year", "id"]`; check constraints `factor_nonnegative`
and `factor_valid_scope` (models.py:30–39). There is **no unique constraint on
`(organisation, name)`** — that is why several factors can share a name
(different years) and the importer disambiguates by `factor_year` or reports
ambiguity. `__str__` returns `"{name} ({year})"` (models.py:41–42).

### `ActivityRecord` (models.py:45)

One calculated activity. Besides the inputs it **snapshots the factor values it
was calculated with** so history stays explainable after the factor changes
(comment models.py:57): `category`, `scope`, `unit`, `factor_value`,
`factor_source`, `factor_year`, `is_demo` are copies of the factor state at
calculation time, not live relations.

| Field | Type / constraint | Reference |
| --- | --- | --- |
| `organisation` | FK → `accounts.Organisation`, required, `CASCADE` | models.py:46 |
| `site` | FK → `accounts.Site`, required, `PROTECT` | models.py:47 |
| `factor` | FK → `EmissionFactor`, required, `PROTECT` | models.py:48 |
| `department` | FK → `accounts.Department`, **optional** (`null=True, blank=True`), `PROTECT` | models.py:49–51 |
| `description` | CharField(160) | models.py:52 |
| `date` | DateField | models.py:53 |
| `quantity` | DecimalField(14, 4), validator ≥ 0 | models.py:54–56 |
| `category` | CharField(100) — snapshot | models.py:58 |
| `scope` | PositiveSmallIntegerField, choices 1–3 — snapshot | models.py:59 |
| `unit` | CharField(30) — snapshot | models.py:60 |
| `factor_value` | DecimalField(16, 8) — snapshot | models.py:61 |
| `factor_source` | CharField(240) — snapshot | models.py:62 |
| `factor_year` | PositiveSmallIntegerField — snapshot | models.py:63 |
| `is_demo` | BooleanField, default `False` — snapshot | models.py:64 |
| `kg_co2e` | DecimalField(20, 2), validator ≥ 0 | models.py:65 |
| `created_by` | FK → `settings.AUTH_USER_MODEL` (= `accounts.User`, settings.py:98), **optional** (`null=True`), `SET_NULL` | models.py:66 |
| `created_at` | DateTimeField, `auto_now_add` | models.py:67 |

Meta: ordering `["-date", "-id"]`; index on `(organisation, date, scope)`;
check constraints `activity_nonnegative` and `emissions_nonnegative`
(models.py:69–79). `__str__` returns `description` (models.py:81–82).

### `ImportLog` (models.py:85)

One CSV-import attempt (bookkeeping only; see section 4 for why it has no FK to
`ActivityRecord`). Nested `Outcome` `TextChoices`: `SUCCESS`, `REJECTED`,
`FAILED` (models.py:86–90).

| Field | Type / constraint | Reference |
| --- | --- | --- |
| `organisation` | FK → `accounts.Organisation`, required, `CASCADE` | models.py:91 |
| `created_by` | FK → `accounts.User`, **optional** (`null=True`), `SET_NULL` | models.py:92 |
| `original_name` | CharField(255) | models.py:93 |
| `stored_file` | FileField, `upload_to="private/emissions-imports/"`, **optional** (`blank=True`; empty until storage save succeeds, cleared again on database failure) | models.py:94 |
| `outcome` | CharField(12), choices `success` / `rejected` / `failed` | models.py:95 |
| `row_count`, `accepted_count`, `rejected_count`, `created_count` | PositiveIntegerField, default 0 | models.py:96–99 |
| `error_messages` | JSONField, default `[]`, blank | models.py:100 |
| `created_at` | DateTimeField, `auto_now_add` | models.py:101 |

Meta: ordering `["-created_at", "-id"]` (models.py:103–104). `__str__` returns
`"{original_name}: {outcome}"` (models.py:106–107).

## 2. Calculation and import classes

### `EmissionsError(ValueError)` — calculations.py:6

Domain exception: "An activity cannot be calculated with the supplied inputs."
Raised by `CO2eCalculator`, `CsvImporter` helpers and the service functions;
inheritance from `ValueError` is the only inheritance edge in this group.

### `CO2eCalculator` — calculations.py:10

Stateful value calculator for **one** factor (a real difference from the draft
`CO2eCalculator(factors: dict)` sketch). Holds private `_kg_per_unit: Decimal`
and `_unit: str`; no public attributes.

| Public method | Behaviour | Reference |
| --- | --- | --- |
| `__init__(kg_per_unit, unit)` | delegates to `set_factor` | calculations.py:11–12 |
| `set_factor(kg_per_unit, unit)` | converts to `Decimal`, rejects empty/blank unit | calculations.py:14–19 |
| `get_factor()` | returns stored kg per unit | calculations.py:21–22 |
| `get_unit()` | returns stored unit | calculations.py:24–25 |
| `calculate(quantity, unit) → Decimal` | rejects a different unit ("automatic unit conversion is not supported"), rejects non-finite/negative input, multiplies at context precision 40, raises on overflow above `999999999999999999.99`, quantizes to 2 decimals with `ROUND_HALF_UP` | calculations.py:37–46 |

Private static helper `_decimal(value)` (calculations.py:27–35) raises
`EmissionsError` for invalid, non-finite or negative numbers.

### `CsvImporter` — csv_import.py:34

Parses and validates CSV **text** without touching the database; the view and
service inject the company's objects as name maps. Module constants:
`REQUIRED_COLUMNS = ("date", "description", "site", "factor", "quantity", "unit")`
and `MAX_ROWS = 5000` (csv_import.py:16–17). Optional columns: `department`,
`factor_year`.

Constructor: `__init__(text, *, sites_by_name, factors_by_name,
departments_by_name=None, today=None)` (csv_import.py:42–49).
`sites_by_name` and `factors_by_name` map a stripped name to a **list** of
objects so ambiguous names are reported instead of silently picking one;
`departments_by_name` maps a name to a single object. The database enforces
unique site and department names per organisation (accounts/models.py:35–39,
57–61), yet sites still use the list form; for factors, which have no such
constraint, the list form is what lets the importer report several same-name
versions instead of silently picking one.
`today` is injectable so the future-date rule is testable.

| Public method | Behaviour | Reference |
| --- | --- | --- |
| `get_text()` | returns stored CSV text | csv_import.py:51–52 |
| `set_text(text)` | replaces text; raises `EmissionsError` for non-string input | csv_import.py:54–57 |
| `parse() → (activities, errors)` | whole-file validation; returns `(list[ImportedActivity], list[{"row": int, "message": str}])`. Handles empty file, duplicate header columns, missing required columns, rows wider than the header, blank-row skipping, the 5 000-row cap and `csv.Error`; returns a "no activity rows" error for an all-empty file | csv_import.py:59–102 |

Row-level private helpers: `_normalise_headers` (csv_import.py:104–109),
`_normalise_row` (111–115), `_parse_row` (117–186: department lookup, required
description ≤ 160 chars, ISO date not in the future, site/factor matching,
quantity parsing, unit must equal `factor.unit`, and a `CO2eCalculator` dry run
before the row is accepted), `_match_site` (188–196), `_match_factor`
(198–214: optional `factor_year` disambiguation, ambiguity errors),
`_parse_quantity` (216–230: finite, non-negative, < 10 000 000 000, at most
four decimal places), `_error` (232–234).

### `ImportedActivity` — csv_import.py:20–31

`@dataclass(frozen=True)`; a validated row awaiting persistence, **not** a model.

| Field | Type | Notes |
| --- | --- | --- |
| `row_number` | int | CSV line number for error messages |
| `date` | `datetime.date` | |
| `description` | str | |
| `site` | `accounts.Site` object | reference carried until saving |
| `factor` | `EmissionFactor` object | reference carried until saving |
| `quantity` | `Decimal` | |
| `unit` | str | |
| `department` | `accounts.Department` object, default `None` | the only optional field |

## 3. Module-level service functions — `backend/emissions/services.py`

These are **functions, not classes**; the UML must not invent a `Service`
class. Each writes domain state and raises `EmissionsError` for domain
violations; the first four are decorated `@transaction.atomic`
(services.py:18, 41, 69, 112).

| Function | Signature | Behaviour | Reference |
| --- | --- | --- | --- |
| `create_activity` | `(*, organisation, created_by, factor, site, quantity, unit, **fields) → ActivityRecord` | Rejects a factor/site from another organisation, computes `kg_co2e` with `CO2eCalculator`, snapshots factor fields, creates the record | services.py:19–38 |
| `update_activity` | `(record, *, refresh_factor=False, **fields) → ActivityRecord` | Rejects cross-organisation changes; refreshes the snapshots only when the factor changed or `refresh_factor=True`; otherwise recalculates from the stored `factor_value`/`unit` | services.py:42–66 |
| `recalculate_factor_records` | `(*, organisation, factor, actor) → int` | `select_for_update` over the organisation's records of one factor; recomputes each via `update_activity(refresh_factor=True)`; writes one UPDATE audit entry per changed record (before/after serializer snapshots in `AuditLog.changes`); returns the changed count. Imports `ActivityRecordSerializer` inside the function to avoid a circular import (comment services.py:84–86) | services.py:70–109 |
| `import_activities` | `(*, organisation, created_by, text) → (int, errors)` | Builds name→object maps from the database (sites, factors, departments), runs `CsvImporter(...).parse()`; on any error saves nothing and returns `(0, errors)`; otherwise creates every row via `create_activity` plus a CREATE audit entry each | services.py:113–146 |
| `persist_import` | `(*, organisation, created_by, original_name, uploaded_file, text) → (ImportLog, int, errors)` | Creates an `ImportLog` (outcome `failed`), stores the file privately under `private/emissions-imports/{org}/{uuid}.{suffix}`, then saves activities inside one atomic block; sets outcome/counts (`row_count = created + distinct rejected rows`, `accepted_count = created_count = created`); on `DatabaseError` deletes the stored file, marks the log `failed` with a generic message (no internal details) and re-raises; `OSError` from storage is recorded and re-raised | services.py:149–216 |
| `scope_totals` | `(records) → dict[int, Decimal]` | `Sum("kg_co2e")` grouped by scope, each total quantized to 0.01; missing scopes are `0.00` | services.py:219–223 |
| `totals_by_scope` | `(organisation, start, end) → dict[int, Decimal]` | kg CO2e per scope for `start ≤ date < end`; the read-only seam documented in `docs/emissions-totals-api.md` | services.py:226–231 |

Related helpers outside this module: `calculate_inputs(data)` in
`serializers.py:44–51` (module function used by serializer validation) and
`filtered_activities(request)` in `views.py:81–93` (module function building
the org-scoped, filtered queryset).

### Orchestration flows (prose, for diagram notes)

1. **Web form create** — `ActivityRecordViewSet.perform_create`
   (views.py:117–118) → `OrganisationScopedMixin.perform_create`
   (accounts/mixins.py:22–27: attaches the user's organisation, records a
   CREATE audit) → `ActivityRecordSerializer.create` (serializers.py:145–146)
   → `create_activity` → `CO2eCalculator`. Update/delete audit happens in the
   viewset's `perform_update`/`perform_destroy` (views.py:135–154).
2. **Preview** — `CalculationView.post` (views.py:219–225) →
   `CalculationSerializer.validate` (serializers.py:69–80): uses the stored
   snapshot when the request targets the activity's own factor, else
   `calculate_inputs`; no persistence.
3. **CSV import** — `ActivityRecordViewSet.import_csv` (views.py:156–193)
   preflight (file present, ≤ 5 MB, UTF-8 decode) → `persist_import` →
   `import_activities` → `CsvImporter.parse` → `create_activity` per row;
   history is read back by `ImportHistoryView` (views.py:196–216,
   `GET /api/emissions/imports/`, last 100 logs).
4. **Factor correction** — `EmissionFactorViewSet.recalculate` (views.py:58–74)
   checks a stale-confirmation 409 first, then `recalculate_factor_records`.
   `EmissionFactorSerializer.validate` (serializers.py:14–21) forbids changing
   a factor's unit/scope ("Add a new factor to change its unit or scope."), and
   the viewset has no destroy route, so referenced factors are never deleted
   (matching the `PROTECT` rule on `ActivityRecord.factor`).
5. **Totals** — `SummaryView` (views.py:228–242) and the analytics/assistant
   consumers go through `scope_totals` / `totals_by_scope`; the assistant reads
   them via `core.emissions_data.totals_by_scope` (core/emissions_data.py:20–25).

## 4. Relationships — optionality and deletion rules, verified

Cross-checked against `models.py` and migrations `0001_initial` /
`0002_activityrecord_department` / `0003_importlog` /
`0004_alter_importlog_stored_file`.

| Source | Field | Target | Required? | `on_delete` | Multiplicity (source side → target side) |
| --- | --- | --- | --- | --- | --- |
| `EmissionFactor` | `organisation` | `accounts.Organisation` | yes | CASCADE | `0..*` factor → `1` organisation |
| `ActivityRecord` | `organisation` | `accounts.Organisation` | yes | CASCADE | `0..*` record → `1` organisation |
| `ActivityRecord` | `site` | `accounts.Site` | yes | PROTECT | `0..*` record → `1` site |
| `ActivityRecord` | `factor` | `EmissionFactor` | yes | PROTECT | `0..*` record → `1` factor (one factor per many records — the proposal's "many ActivityRecords use one EmissionFactor") |
| `ActivityRecord` | `department` | `accounts.Department` | **no** (`null=True, blank=True`) | PROTECT | `0..*` record → `0..1` department |
| `ActivityRecord` | `created_by` | `accounts.User` | **no** (`null=True`) | SET_NULL | `0..*` record → `0..1` user |
| `ImportLog` | `organisation` | `accounts.Organisation` | yes | CASCADE | `0..*` log → `1` organisation |
| `ImportLog` | `created_by` | `accounts.User` | **no** (`null=True`) | SET_NULL | `0..*` log → `0..1` user |

Semantics of the deletion rules: deleting an organisation removes its factors,
activities and import logs (CASCADE); sites, factors and departments
referenced by activities cannot be deleted while referenced (PROTECT); deleting
a user keeps the records/logs with `created_by = NULL` (SET_NULL).

**No `ActivityRecord` ↔ `ImportLog` foreign key exists, in either direction.**
Verified by reading `models.py` and searching the whole `backend/emissions/`
package (models, migrations 0001–0004, services, views, tests) for `ImportLog`
references: `ImportLog` links only to `Organisation` and `created_by`, and the
sole trace of which activities an import created is the `created_count`
number on the log. Any import→activity association in a diagram would be
invented.

External classes referenced by the FKs (owned by the accounts subsystem,
`backend/accounts/models.py`, drawn only as boxes with minimal attributes):
`Organisation` (:9), `Site` (:25, unique `(organisation, name)`),
`Department` (:45, unique `(organisation, name)`), `User` (:67, `AbstractUser`
with optional organisation FK and role choices). `AuditLog` (:169) is written
by the services via `record_audit` (accounts/services.py:22) using string
`object_type`/`object_id` references — no database FK from emissions to
`AuditLog`, so it needs no diagram edge.

Transient object usage (no database edges): `CsvImporter` receives site/
factor/department objects through its name maps and emits `ImportedActivity`
values carrying references to them; `persist_import` turns each accepted value
into an `ActivityRecord` via `create_activity`. `CO2eCalculator` is
instantiated per calculation and shared by the services, the importer's dry
run (csv_import.py:170) and serializer validation (serializers.py:47–51,
73–77, 133–139). `EmissionsError` is the shared failure type of all of these.

## 5. HTTP/serialisation layer (implemented; excluded from the class diagram)

Listed for inventory completeness; Django/DRF infrastructure is omitted from
the diagram per the delivery plan.

- `EmissionFactorViewSet` (views.py:30–74) — list/retrieve/create/update plus
  the `recalculate` POST action; permission `CanEditDataOrReadOnly`.
- `ActivityRecordViewSet` (views.py:96–193) — CRUD plus the
  `POST /api/emissions/activities/import/` action (`import_csv`); page
  pagination 20/page via `ActivityPagination` (views.py:77–78).
- `ImportHistoryView` (views.py:196–216), `CalculationView`
  (views.py:219–225), `SummaryView` (views.py:228–242) — APIViews.
- Serializers (serializers.py): `EmissionFactorSerializer` (:13),
  `CompanyRelationsMixin` (:28, scopes FK querysets to the user's
  organisation), `CalculationSerializer` (:54), `ActivityRecordSerializer`
  (:83, read-only snapshot fields), `ActivityFilterSerializer` (:149).
- `EmissionsConfig` (apps.py:4) and the seed command class `Command`
  (management/commands/seed_official_factors.py:15) — the latter inserts
  reviewed factors from `backend/emissions/data/official_factors.json` into
  one explicit organisation; its package markers are the untracked
  `management/__init__.py` files flagged for task D03.
- Routes in urls.py:12–20 register `factors/`, `activities/` plus
  `preview/`, `summary/`, `imports/`.

## 6. Streaming pipeline classes (separate homework path; excluded from the diagram)

`backend/emissions/streaming.py` adapts the team's homework stream package
(`stream_processing.base`): `ScopeFilter` (streaming.py:20) and
`EmissionTransformer` (streaming.py:41) extend `StreamProcessor`;
`ActivityStream` is a re-export alias of `EventSource` (streaming.py:16).
`EmissionTransformer` reuses `CO2eCalculator` and raises `EmissionsError` for
unknown factors (streaming.py:41–65). These operate on `ActivityEvent` values,
not Django models, and stay out of the web-subsystem diagram.

## 7. Diagram guidance for the D04 worker

- Show: `EmissionFactor`, `ActivityRecord`, `ImportLog`, `CO2eCalculator`,
  `CsvImporter`, `ImportedActivity`, `EmissionsError`, plus external
  `Organisation`, `Site`, `Department`, `User` boxes for ownership.
- Methods: public operations only, exactly as in sections 1–2 (`parse`,
  `set_text`/`get_text`, `calculate`, `set_factor`/`get_factor`/`get_unit`);
  no `__str__` boilerplate, no invented methods.
- Edges: the eight FK rows of section 4 with their multiplicities (draw
  `department` and `created_by` as optional); the generalisation
  `EmissionsError --|> ValueError` (triangle pointing at `ValueError`); do
  **not** draw an activity↔import-log association. If a
  usage edge is wanted, a dashed dependency from `CsvImporter` to
  `ImportedActivity`/`CO2eCalculator` reflects real code.
- The five orchestration flows of section 3 belong in diagram notes or
  accompanying prose, not as a service class.

## 8. Checks performed and limitations

- Read in full: `models.py`, `calculations.py`, `csv_import.py`, `services.py`,
  `serializers.py`, `views.py`, `streaming.py`, `urls.py`, migrations
  `0001`–`0004`, `accounts/models.py`, `accounts/mixins.py`,
  `core/emissions_data.py`, the seed command; grep checks across
  `backend/emissions/` for `ImportLog` and `record_audit` usage; `AUTH_USER_MODEL`
  confirmed as `accounts.User` (config/settings.py:98); proposal slide 2 XML
  extracted to compare the draft class sketch against the implementation.
- FK optionality/`on_delete` verified against both models and migrations.
- Documentation task: no runtime suite was rerun. Per the delivery plan, the
  latest recorded evidence is the run recorded in `docs/emissions-delivery-plan.md`
  (271 tests passed, Django check and Ruff checks passed), attributed to that
  recorded run and not re-verified here. No application code was changed; this
  file is the only file touched.
- Limitation: line numbers reflect the `4aa24d7` working tree and can drift;
  the content, not the line numbers, is the contract for the UML.

## 9. Diagram rendering (task D05)

The diagram source is `docs/diagrams/emissions-classes.mmd`. It was
rendered with Mermaid CLI **12.2.0** (`@mermaid-js/mermaid-cli`) using Node.js
v22.19.0 and npm/npx. No project dependency or global install is needed. From
the repository root, npx downloads/runs the pinned CLI package version:

```sh
npx --yes --package @mermaid-js/mermaid-cli@12.2.0 mmdc --version
npx --yes --package @mermaid-js/mermaid-cli@12.2.0 mmdc \
  -i docs/diagrams/emissions-classes.mmd \
  -o docs/diagrams/emissions-classes.svg -b white
npx --yes --package @mermaid-js/mermaid-cli@12.2.0 mmdc \
  -i docs/diagrams/emissions-classes.mmd \
  -o docs/diagrams/emissions-classes.png -b white -s 2
```

The worker reported successful renders with Mermaid CLI 12.2.0; the commands
above use explicit npx package selection for reproducibility. The PNG
measured **1568 × 596 px**. The CLI uses its bundled Puppeteer/Chromium setup;
no custom browser path or Puppeteer configuration was required. Thus there is
no `/tmp` config or browser path to reproduce. If a machine requires a custom
browser configuration, Mermaid CLI accepts `-p <puppeteer-config.json>`; that
is environment-specific and was not used for these artifacts.

For readability, the source layout uses `direction TB` instead of `direction
LR`. The six note labels were shortened to concise summaries; complete class,
field, behavior, and relationship explanations remain in this inventory.
No class or relationship semantics were changed. The PNG has small text when
viewed as a full-page image, so zoom or inspect crops for detail; the SVG is
scalable and suited to zooming.
