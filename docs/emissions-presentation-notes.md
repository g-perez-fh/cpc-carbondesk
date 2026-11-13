# Guillermo's emissions presentation notes and repeatable demo

Status: **speaking outline + demo script**, written 11 November 2026 as delivery
task D06 of `docs/emissions-delivery-plan.md`. Owner of the material:
Guillermo Pérez Pérez (Emissions Data & Calculation). This document prepares a
modular explanation and a reproducible demo; it is **not** a finished team
presentation, contains no slides, and creates no recording or video link (the
team adds the real link later; no placeholder link is valid).

Everything here describes the implemented code on branch
`feature/emissions-import-history` (revision `97c11b5`, factor-seed commit
`4aa24d7`). Line numbers reflect that working tree and can drift. All demo
data is **synthetic** and labelled as such; the numbers are for software
demonstration, not real emissions estimates.

## 1. Presentation formats — three different durations, not one

| Requirement | Source | Value |
| --- | --- | --- |
| Live team presentation | `capstone project requirements 2026 python.pdf`, p. 7 | **15–20 minutes**, containing roles distribution, domain description, system requirements, a UML class diagram per subsystem, how each subsystem functions, and unit-test results. "Each team member evaluated separately." |
| Recorded screencast | `capstone project requirements 2026 python.pdf`, p. 4 | **7 minutes**, link uploaded to the repository README |
| Recorded video (final reminder) | `Instuctions last weeks-1.pdf`, p. 1 | **5-minute video** in the README |

The 7-minute and 5-minute recording figures are **still unresolved**; the team
must pick one (see `docs/emissions-delivery-plan.md`, "Sources to read", and
`docs/emissions-delivery-evidence.md` section 6). Guillermo should not record
two videos. The material below is modular so it can serve the live 15–20 minute
presentation and either recording length once the team decides.

(Page numbers above were re-verified by text extraction on 11 November 2026.)

## 2. Modular timing — per module, not a team allocation

The durations below are estimates for Guillermo's contribution alone. The team
decides how the 15–20 minutes and the video minutes are divided across members;
nothing here proposes that split.

| Module | Content | Time |
| --- | --- | --- |
| M0 | Demo setup (prepare beforehand, show briefly) | ~1 min or pre-staged |
| M1 | Activity form: preview and save 100 kWh × 0.4 = 40.00 kg CO2e | ~2 min |
| M2 | Invalid form save (future date rejected) | ~0.5–1 min |
| M3 | Valid CSV import + import history endpoint | ~2 min |
| M4 | Invalid CSV import: all-or-nothing and counters | ~1.5 min |
| M5 | Snapshots vs explicit recalculation | ~2.5 min |
| M6 | Audit history: what exists, where to show it, limits | ~1 min |
| M7 | Permissions and the totals other subsystems consume | ~1.5 min (mostly talking) |

Suggested assemblies (his choice, not a rule):

- **Live presentation, core cut (~6–7 min):** M0 → M1 → M3 → M5 → short M6/M7
  talking points. Mention M2/M4 validation rules verbally instead of clicking
  through them.
- **Recording subset (~3 min of his contribution):** M1 + M3 or M5, depending
  on what the team wants the video to show.
- **Full set (~10 min):** all modules, only if the team gives the emissions
  subsystem that much room.

## 3. What Guillermo must be able to explain (class responsibilities)

Use `docs/emissions-class-inventory.md` (task D01) as the authoritative list;
the outline below is the speaking order. Three kinds of things exist in
`backend/emissions/`, and saying so is part of the story:

1. **Django models** (persistence only, `__str__` excepted): `EmissionFactor`
   (models.py:10), `ActivityRecord` (models.py:45), `ImportLog` (models.py:85).
2. **Plain Python classes**: `CO2eCalculator` (calculations.py:10) — holds one
   factor and converts a quantity to kg CO2e; `CsvImporter` (csv_import.py:34) —
   parses and validates CSV text without touching the database;
   `ImportedActivity` (csv_import.py:20) — a frozen dataclass carrying one
   validated row until it is saved; `EmissionsError(ValueError)`
   (calculations.py:6) — the shared domain failure type.
3. **Module-level service functions** (services.py) — deliberately **no**
   `Service` class; the proposal's draft diagram sketched methods on the models
   (e.g. `calc_co2e()` on `ActivityRecord`); the implementation moved behaviour
   into these functions. Say this openly as a design evolution, not a defect:
   `create_activity` (19–38), `update_activity` (41–66),
   `recalculate_factor_records` (69–109), `import_activities` (112–146),
   `persist_import` (149–216), `scope_totals` (219–223), `totals_by_scope`
   (226–231).

The one-sentence flow to memorise: **input → validation → calculation →
persistence (+ audit)** — a view/serializer accepts input, `CO2eCalculator`
computes with `Decimal`, the service saves the record with factor snapshots and
writes an `AuditLog` entry, all inside one database transaction.

## 4. Demonstration prerequisites

Do these **before** the demo; none of them needs credentials from this
document — choose demo passwords privately and never reuse real ones on camera.

1. **Environment is already running.** Per `docs/emissions-delivery-evidence.md`
   section 3, `docker compose up --build -d` was started in this checkout
   (prior recorded run): `db` (PostgreSQL 17), `backend` on 127.0.0.1:8000 and
   `frontend` on 127.0.0.1:8080, all `Up (healthy)`. Sanity-check with
   `docker compose ps` before presenting; restart with `docker compose up -d`
   if needed. Healthcheck probes are shallow — the demo itself is the
   functional verification on this revision (no full browser-demo verification
   exists yet; see section 15, "Unresolved").
2. **A separate demo organisation.** Register a fresh company at
   http://localhost:8080/register — the registering user becomes its
   administrator (README, "Current status"). Use an obviously demo name such as
   "Presentation Demo Co". A second organisation can be registered later for
   the isolation talking point in M7.
3. **Site.** On the Organisation page, add site "Main office" (admin action).
4. **Synthetic factor.** On Emissions → Emission factors, "Add an emission
   factor": name `Demo electricity`, Scope 2, unit `kWh`, value `0.4`, source
   `Synthetic example`, year `2026`, and tick **"This is a synthetic demo
   factor"** (frontend/pages/emissions.py:336; README "First emissions
   workflow" documents the same recipe). State clearly that 0.4 is an invented
   test value, not a published factor. The reviewed UK DESNZ 2025 seed exists
   (`.venv/bin/python backend/manage.py seed_official_factors
   --organisation-id <ID>`, docs/emission-factor-sources.md:87) but is **not**
   part of this demo.
5. **Two CSV files** prepared in advance (exact text in M3/M4). The import
   dialog also offers "Download template" producing the same shape
   (frontend/pages/emissions.py:14–17).
6. **Admin access for audit history (M6).** Create a Django superuser once:
   `docker compose exec backend python manage.py createsuperuser` (README).
   This is only for opening http://localhost:8000/admin/ to show audit rows.
7. The two empty package-marker files `backend/emissions/management/__init__.py`
   and `backend/emissions/management/commands/__init__.py` are untracked; per
   `docs/emissions-delivery-evidence.md` section 4 they do not affect the venv
   or Docker demo. Include them when staging (user decision, not an agent one).

## 5. M0 — demo starting state

Fresh demo organisation contains: 1 site ("Main office"), 1 factor ("Demo
electricity", 0.4 kg CO2e/kWh, `is_demo=True`), **0 activities**, so
`GET /api/emissions/summary/` returns `count: 0`, `demo_count: 0`,
`total_kg_co2e: "0.00"`, scopes `"0.00"` (SummaryView, views.py:228–242; pinned
by `test_emissions.py::test_summary_shape_units_and_empty_scope`). The page
shows the empty state "No activity records yet" with the hint to add a factor
and a site first (frontend/pages/emissions.py:183–194).

## 6. M1 — form save: 100 kWh × synthetic 0.4 = 40.00 kg CO2e

**Steps.** "Add activity" opens the "Record an activity" dialog; fill
description "October office electricity", today's date, site "Main office",
factor "Demo electricity · 2026 · Demo". The quantity label renames itself to
"Quantity (kWh)" and a details line shows the factor
"Scope 2 · 0.4 kg CO₂e/kWh · Synthetic example (2026)"
(frontend/pages/emissions.py:551–557). Press **"Preview calculation"** → the
preview box shows **"Calculated emissions: 40.00 kg CO2e"** (frontend/
components.py:30–32 formats it; POST `/api/emissions/preview/`, no persistence).
Press **"Save activity"** → notification **"Activity saved · 40.00 kg CO2e"**.

**Then show.** The summary box: total "40.00 kg CO2e", "Activities: 1 · current
filters", Scope 2 · Energy 40.00, and the amber label "Includes 1 activities
calculated with demo factors. These are not verified emissions."
(frontend/pages/emissions.py:159–181). Open the record's details dialog: it
shows "100 kWh × 0.4 kg CO₂e/kWh", factor/source/year, the demo label, and
"Rounded to 0.01 kg CO₂e. The factor inputs are preserved with this record."
(frontend/pages/emissions.py:615–637) — this is the **snapshot** talking point.

**Code to name:** serializer validation calls `calculate_inputs`
(serializers.py:44–51) → `CO2eCalculator.calculate` multiplies with `Decimal`
at precision 40, rejects unit mismatch/overflow, quantizes once to 0.01 with
`ROUND_HALF_UP` (calculations.py:37–46) → `create_activity` snapshots factor
fields onto the record and saves (services.py:19–38) → the viewset mixin writes
a CREATE audit entry (accounts/mixins.py:22–27).

**Pinned by** (recorded run, see section 14):
`test_emissions.py::test_create_record_calculates_and_audits` (48–61: body
`kg_co2e == "40.00"`, scope 2, `factor_source == "Synthetic test factor"`,
`is_demo is True`, one CREATE audit) and
`test_emissions.py::test_preview_matches_saved_calculation` (64–72: preview
2.5125 × 0.4 → "1.01" and **0 records written**).

## 7. M2 — invalid form save (quick)

Set the activity date to **tomorrow** (whatever the demo day is) and press
"Save activity". Expected: a red notification carrying the backend message
"Activity dates cannot be in the future." (serializers.py:120–123; the frontend
shows backend errors via `call_api` → `ui.notify(..., type="negative")`,
frontend/components.py:14–23), the dialog stays open, nothing is saved, and the
summary still shows 1 activity.

Note honestly if asked: the NiceGUI form always sends the selected factor's own
unit, so a **unit mismatch** is not reachable through this dialog — that rule
is demonstrated with CSV (M4) and pinned at the API level.
Pinned by `test_emissions.py::test_invalid_activity_does_not_write` (75–99):
12 invalid variants each return 400 with **no record and no audit row**.

## 8. M3 — valid CSV import, then the history endpoint

**File `demo-valid.csv`** (header + 2 data rows; `factor_year` is optional but
shown here, matching the shipped template):

```csv
date,description,site,factor,factor_year,quantity,unit
2026-01-31,January office electricity,Main office,Demo electricity,2026,100,kWh
2026-02-01,February office electricity,Main office,Demo electricity,2026,2.5125,kWh
```

**Steps.** "Import CSV" → choose the file → upload. Expected response body:
`{"created": 2, "unit": "kg CO2e"}` with HTTP 201 (views.py:156–193).

**Expected state after this module** (cumulative with M1): 3 records, summary
`count: 3`, `demo_count: 3`, `total_kg_co2e: "81.01"` (40.00 + 40.00 + 1.01),
Scope 2 81.01.

**Rounding talking point:** row 2 is 2.5125 × 0.4 = 1.005 → stored as **1.01**
because rounding happens once per record, half up (calculations.py:37–46;
README wording: "rounds half up to 0.01 kg CO2e once per record; totals sum
those saved results"). Totals add **already-rounded** record values, so 40.00 +
40.00 + 1.01 = 81.01, not 81.005.

**Import history — backend endpoint only.** Show
`GET /api/emissions/imports/` with a token-authenticated call (a plain browser
address bar has no session on port 8000 — the NiceGUI login token is held by
the frontend server, not the browser, so an unauthenticated browser gets 401):

```bash
curl -s -X POST http://127.0.0.1:8000/api/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "<demo-admin-username>", "password": "<demo-admin-password>"}'
# → {"token": "...", "user": {...}}; then:
curl -s -H "Authorization: Token <paste-token>" http://127.0.0.1:8000/api/emissions/imports/
```

Use his own demo credentials; this document contains none. Expected: one
entry, `outcome: "success"`, `row_count: 2`, `accepted_count: 2`,
`created_count: 2`, `rejected_count: 0`. **There is no NiceGUI history page** —
say that out loud. The proposal sketched an import-history UI; the delivered
scope is the JSON endpoint (views.py:196–216, last 100 attempts) and a history
UI was deferred deliberately (`docs/emissions-delivery-plan.md`, Scope).
Do not click around looking for a history page on camera.

**Pinned by:** `test_csv_import.py::test_valid_csv_imports_and_calculates`
(48–62: created 2; stored kg_co2e values `[40.00, 1.01]`; 2 CREATE audits) and
`test_import_history.py::test_success_rejected_and_failed_outcomes_appear`
(126–…, all three outcomes in one history). The counting contract is
`docs/emissions-import-contract.md`.

## 9. M4 — invalid CSV import: all-or-nothing and the counters

**File `demo-invalid.csv`** (the bad row is the **third physical line** — the
header counts as line 1, which is what "Row 3" refers to):

```csv
date,description,site,factor,factor_year,quantity,unit
2026-01-31,January office electricity,Main office,Demo electricity,2026,100,kWh
31-01-2026,Bad row,Main office,Demo electricity,2026,100,litres
```

**Expected response:** HTTP 400 with exactly these two messages for that one
row (csv_import.py:140 and :164 produce the texts; the view prefixes "Row N:",
views.py:183–192):

```json
{"file": ["Row 3: Use a date in YYYY-MM-DD format.",
          "Row 3: Unit 'litres' does not match the factor unit 'kWh'."]}
```

**Nothing is saved** — no activities, no audit entries; the summary is
unchanged (count 3, total 81.01). That is the all-or-nothing rule
(services.py:130–131 returns before saving any row).

**History entry to show:** `outcome: "rejected"`, `row_count: 1`,
`rejected_count: 1`, `accepted_count: 0`, `created_count: 0`. The honest nuance
to state: the file had 2 data rows but `row_count` is 1 — the **valid row is
not counted anywhere** on a rejected batch, because counts are derived from
saved records plus rejected rows (services.py:183–189). This is a documented
limitation of the current counting rule, not a bug being hidden
(`docs/emissions-import-contract.md`, "Known limitation"). One row can also
produce several messages, which is why `rejected_count` counts **rows**, not
messages.

**Pinned by:** `test_csv_import.py::test_unit_must_match_the_factor` (136–142),
`test_csv_import.py::test_invalid_values_are_reported` (249–253: future date,
negative, five-decimal quantities each rejected with nothing written),
`test_csv_import.py::test_malformed_row_reports_line_number_and_writes_nothing`
(108–…), and `test_import_history.py::test_header_only_file_is_rejected_with_its_own_counters`
(166–…: a header-only file is a rejection with `row_count = 1`).

## 10. M5 — snapshots vs explicit recalculation (the core design point)

**Step 1 — correct the factor.** "Edit factor" on "Demo electricity": change
the value to `0.8` and the source to `Synthetic example (corrected)`. The dialog
warns **"Saving does not recalculate existing activities."** and disables the
scope/unit fields (frontend/pages/emissions.py:349–353; unit/scope changes are
forbidden server-side too — "Add a new factor to change its unit or scope.",
serializers.py:14–21).

**Step 2 — show that saved data did not move.** The record still shows
40.00 kg CO2e; the summary still shows 81.01. In the record's "Edit activity"
dialog, "Preview calculation" **still returns 40.00**: because the record's
factor is unchanged, the preview intentionally uses the **stored snapshot**
`factor_value`/`unit`, not the factor's new value (serializers.py:69–80,
`update_activity` docstring services.py:41–43). Frame the chosen rule as our
team decision, not a professor requirement: stored results keep the factor
values they were calculated with until an explicit recalculation runs
(services.py:69–83 docstring says exactly this).

**Step 3 — explicit recalculation.** "Recalculate activities" → dialog
"Recalculate linked activities?" → confirm. Expected notification:
**"Recalculated N activities"** (`{"updated": N}`; N is 3 in the full flow
above — 1 form record + 2 imported rows — or 1 if only M1 ran, so state the
number from the data actually present). The HTTP action is
`POST /api/emissions/factors/<id>/recalculate/`, views.py:58–74, which checks a
stale-confirmation first. Expected state in the full flow: records 80.00 /
80.00 / 2.01 (2.5125 × 0.8 = 2.01), summary total **162.01**, Scope 2 162.01.
The operation is atomic and locks the affected rows (`select_for_update`).

**Pinned by:** `test_emissions.py::test_factor_correction_and_explicit_recalculation`
(389–413: after PATCH to 0.8 the record stays 40.00; preview on the saved
record returns "40.00"; recalculate → `updated == 1`; record becomes 80.00 with
the corrected source; audit `before.kg_co2e == "40.00"`, `after.kg_co2e ==
"80.00"`; a second recalculate reports `updated == 0`; and the analytics
dashboard total reads "80.00" — see M7).
`test_activity_history_recalc.py::test_recalculation_touches_only_the_target_factor`
(62–…) shows recalculation is scoped to one factor within the organisation.

**If it happens on camera:** confirming recalculation after someone else
changed the factor returns HTTP 409 "The factor changed. Refresh and confirm
again." (views.py:62–67; pinned by
`test_emissions.py::test_factor_stale_confirmation`, 423–428). Explain it as
protection against stale confirmation dialogs, refresh, and continue.

## 11. M6 — audit history: what exists, where to show it, limits

**What exists:** an append-only `AuditLog` owned by the accounts subsystem
(accounts/models.py:169–194). Emissions writes: one CREATE entry per
created/imported activity, one UPDATE entry per edited record with
`{"before": …, "after": …}` (views.py:135–153), one UPDATE entry per changed
record during recalculation carrying `reason: "factor_recalculation"` with
before/after serializer snapshots (services.py:102–107), and a DELETE entry
keeping the record's details (views.py:147–153). There is no FK from emissions
to `AuditLog` — string references only (D01 inventory, section 4).

**Where to show it in the demo (recommended):** Django admin at
http://localhost:8000/admin/ → Audit logs (read-only there,
accounts/admin.py:38–42). Open the recalculation entries and show
`before.kg_co2e "40.00"` → `after.kg_co2e "80.00"`. The admin works for all
entry shapes. JSON alternative: `GET /api/accounts/audit-log/` (admin-only,
`IsOrganisationAdmin`, accounts/views.py:219–223, 50 per page, latest first)
using the **demo organisation admin's** token from the same login call as M3 —
the `createsuperuser` account is not an organisation member and gets 403 on
this endpoint.

**Honest limitation — do not demo the NiceGUI Audit log tab here.** The
Organisation page has an admin-only "Audit log" tab, but its row builder
renders every change as `field: from → to` (frontend/pages/accounts.py:401–404).
Emissions UPDATE/DELETE entries store `{"before": …, "after": …}` (and
`reason`) shapes, which that code cannot render (it would raise while building
rows; the other tabs are unaffected because this section loads last). In a demo
where a recalculation or an activity edit has already happened, that table will
not display those entries. This is a known frontend integration limitation,
found while preparing this demo and **reported to the delivery-plan owner for
the review/fix round (D08/D09)** — it is not silently worked around, and the
demo above simply uses the admin/API view instead. CREATE/import and
accounts-side `{field: {from, to}}` entries do render in that tab today.

**Second honest limitation:** there is **no import-history UI** (section 8) —
audit history and import history are different things; only audit history has
any UI beyond JSON at all today.

## 12. M7 — permissions and the totals other subsystems consume

Talking points with code and test anchors (demo clicks optional):

- **Roles.** Both emissions viewsets use `CanEditDataOrReadOnly`
  (accounts/permissions.py:33–39; views.py:42 and :107): admins/editors write,
  viewers read and preview. Preview/summary/imports-history use
  `IsOrganisationMember`. Pinned by `test_emissions.py::test_role_permissions`
  (110–…), `test_factor_write_permissions` (432–…), and
  `test_csv_import.py::test_viewer_cannot_import` (172–…).
  Enforcement is **backend** — hiding a UI button is not the security
  boundary; say this sentence.
- **Organisation isolation.** Querysets are filtered by the user's
  organisation (`OrganisationScopedMixin.get_queryset`, accounts/mixins.py:15–16)
  and foreign-key choices are scoped per company
  (`CompanyRelationsMixin`, serializers.py:28–41). Cross-company factor/site
  IDs are rejected (`test_other_company_references_rejected`,
  `test_other_company_cannot_change_activity`), import history is org-scoped
  (`test_import_history.py::test_history_is_organisation_scoped`), and totals
  never leak (`test_emissions.py::test_records_and_totals_are_isolated`,
  154–…). Optional click: register/keep a second demo organisation; its summary
  shows `count: 0`, `total "0.00"` while the demo org shows 162.01.
- **Consumers.** `SummaryView` serves `GET /api/emissions/summary/` (end
  **exclusive** windows, Decimal-as-string with two decimals, no floats over
  HTTP; `docs/emissions-totals-api.md`). The analytics dashboard reads
  `ActivityRecord` + `scope_totals` read-only, and the assistant reads
  `totals_by_scope` through the deliberate seam `core/emissions_data.py:20–25`
  — neither duplicates the calculation. Pinned consumer tests:
  `test_emissions.py::test_filter_dates_and_consumers_use_real_totals` (166–…)
  and, notably, `test_factor_correction_and_explicit_recalculation` line 413
  asserting the **analytics dashboard** total updates to the recalculated
  value. Optional click: open http://localhost:8080/dashboard and point out the
  same total the emissions page shows (Harib's page — show, don't explain his
  subsystem).

## 13. Practice questions Guillermo should answer personally

He should be able to answer these without notes; pointers are for preparation.

1. Why does the saved activity still show 40.00 after the factor changes to
   0.8, and which exact code path changes it later? (snapshot fields +
   `refresh_factor`; services.py:41–66, 69–109)
2. Where does rounding happen, why once per record, and what is 2.5125 × 0.4?
   (1.005 → "1.01", `ROUND_HALF_UP` to 0.01; calculations.py:37–46)
3. In the rejected import, why is `row_count` 1 when the file had two data
   rows? (all-or-nothing; valid-but-unsaved rows are counted nowhere — a
   documented counting limitation, services.py:183–189)
4. What is the difference between `rejected` and `failed` import outcomes, and
   what happens to the stored file in each? (rejected = validation, file kept;
   failed = storage/database error — on DB failure the stored file is deleted
   and counts stay 0/unknown; fixed safe log messages instead of exception
   text; services.py:149–216, import contract)
5. Why is there no foreign key between `ActivityRecord` and `ImportLog`, and
   what does that mean for tracing what an import created? (only
   `created_count` traces it; a diagram edge would be invented — D01, section 4)
6. Which permission class guards emissions writes, where is it enforced, and
   what exactly can a viewer do? (write via API, not UI hiding; viewer can
   read/preview but any write returns 403)
7. How do the dashboard and assistant get their totals without duplicating
   your calculation? (`scope_totals` / `totals_by_scope` seam, end-exclusive
   windows, `Decimal` values at the seam, strings only at HTTP; and the
   analytics total demonstrably follows a recalculation — test line 413)

## 14. Honest limitations to state (not to hide)

Say these in his own words if the topic comes up; they are the current state,
not claims of full proposal fulfilment:

- **Deferred by the delivery plan** (`docs/emissions-delivery-plan.md`, Scope):
  import-history UI (API exists, UI does not), import-file download endpoints,
  log/file retention decision (open issue 1 of the import contract), factor
  catalogue expansion, performance optimisation, PostgreSQL benchmarking, and
  a backup-restore project (backups are DB-only; upload recovery is open).
- **Audit-log tab rendering** for emissions before/after entries is broken in
  the current frontend (section 11); show audit history via Django admin or the
  audit API until fixed.
- **Rejected-import counting** understates files that contain valid rows
  (section 9).
- **Demo data is synthetic and labelled**: the 0.4 factor, the demo org and the
  CSV rows exist for this demonstration; the page itself prints "These are not
  verified emissions". Published seeds (UK DESNZ 2025) exist separately via the
  documented seed command but are not part of this demo.
- **Evidence is attributed, not fresh**: the latest recorded check run is
  **271 tests passed**, Django `check` clean, `ruff check`/`format --check`
  clean on revision `97c11b5` (11 November 2026), recorded in the delivery plan
  and consolidated in `docs/emissions-delivery-evidence.md` section 2 — a
  **prior recorded run, not re-verified by this task**. The 94 % coverage and
  the ~1.4 s / 5,000-row import benchmark are earlier single-setup **SQLite**
  results (10 November 2026, 240-test suite) and must not be quoted as current;
  no PostgreSQL performance claim exists. If the final revision moves past
  `97c11b5`, re-run the README check set before presenting or recording.
- This document prepared **no slides, no video, no link**; recording and the
  README video link are team work after the 7-min/5-min duration decision.

## 15. Checks performed by this task

Read-only documentation task (D06): no application code, dependencies,
migrations or other documents were changed; the only file written is this one.
No pytest/ruff/`check`/coverage runs, no Docker commands, no browser session.

- Every endpoint, dialog label, notification text, error message and expected
  output above was verified by reading the cited files in the working tree:
  `backend/emissions/{calculations,csv_import,services,serializers,views}.py`,
  `backend/emissions/urls.py`, `backend/emissions/management/commands/seed_official_factors.py`,
  `backend/emissions/tests/*` (test names and bodies), `backend/accounts/{models,views,serializers,services,mixins,permissions,admin}.py`,
  `frontend/pages/emissions.py`, `frontend/pages/accounts.py`,
  `frontend/components.py`, `README.md`.
- Presentation-duration statements were verified by text extraction from
  `capstone project requirements 2026 python.pdf` (pp. 4, 6–7) and
  `Instuctions last weeks-1.pdf` (p. 1).
- Consistency: every referenced document path exists on this checkout
  (`docs/emissions-delivery-plan.md`, `docs/emissions-class-inventory.md`,
  `docs/emissions-delivery-evidence.md`, `docs/emissions-import-contract.md`,
  `docs/emissions-totals-api.md`, `docs/emission-factor-sources.md`).
- Arithmetic in the cumulative expectations was re-checked: 100 × 0.4 = 40.00;
  2.5125 × 0.4 = 1.005 → 1.01; 2.5125 × 0.8 = 2.01; totals 40.00 → 81.01 →
  162.01 after recalculation of 3 records.
- Substantive finding reported to the parent in the task result (not edited
  here, out of scope): the frontend audit-log section's change rendering
  (frontend/pages/accounts.py:401–404) assumes `{field: {from, to}}` shapes and
  cannot render the `{"before", "after"}`/`{"reason", …}` shapes that emissions
  writes (backend/emissions/views.py:135–153, services.py:102–107).
- Unresolved: the 7-minute (requirements p. 4) vs 5-minute (final reminder
  p. 1) recording duration; the demo has never been executed end-to-end on
  this revision (no full browser-demo verification exists yet —
  `docs/emissions-delivery-evidence.md` section 3), so a rehearsal run of
  section 4–12 is Guillermo's first hands-on verification step.
