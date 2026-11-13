# Emissions README corrections — drafts for D07 (task D02)

Updated 11 November 2026. Owner role: documentation worker (task D02 in
`docs/emissions-delivery-plan.md`). Allowed output: this file only. **No README
or code edit was made in this task**; the wording below is proposed for D07 to
apply, with exact placement anchors.

Verified against the worktree at revision `97c11b5` ("chore(infra): add coverage
and database backup tools"), branch `feature/emissions-import-history`, on
11 November 2026. Line numbers refer to `README.md` as read that day and may
shift; the quoted anchor text is authoritative. Every factual claim in the
proposed wording was checked against code (references in each item), not copied
from `dev.md` or the proposal slides.

Checks were documentation checks only (reading, cross-referencing, link and
consistency checks). No test suite, Django check or Ruff run was performed for
this task; no test-count claim should be derived from it.

---

## 1. Summary of proposed corrections

| ID | Target | Kind |
| --- | --- | --- |
| C1 | Main endpoints table, Emissions row | Add `emissions/imports/` |
| C2 | Endpoint behavior | New bullet documenting `GET /api/emissions/imports/` (backend-only, no UI) |
| C3 | CSV import section | Exact response shape, import-history counters, known limitations |
| C4 | New subsection `### Seeding official factors` | Seed command, unit-labelled names, idempotency |
| C5 | Endpoint behavior, summary bullet | Count semantics (filtered window) |
| C6 | Endpoint behavior, recalculate bullet | `{"updated": N}`, audit-entry nuance |
| C7 | First emissions workflow | Demo row using a seeded unit-labelled factor; `is_demo` nuance |

All seven correction items below give: the anchor to find, the action, and
ready-to-paste wording.

---

## 2. Corrections

### C1 — Main endpoints table: add the import-history endpoint

**Anchor** (README line 225, row "Emissions" in the *Main endpoints* table):

```
| Emissions | `emissions/factors/`, `emissions/activities/`, `emissions/activities/import/`, `emissions/preview/`, `emissions/summary/` |
```

**Action:** replace the row with:

```
| Emissions | `emissions/factors/`, `emissions/activities/`, `emissions/activities/import/`, `emissions/imports/`, `emissions/preview/`, `emissions/summary/` |
```

**Verified:** route `path("imports/", ImportHistoryView...)` in
`backend/emissions/urls.py` (line 19), included under `api/emissions/` in
`backend/config/urls.py` (line 7). Full URL: `GET /api/emissions/imports/`.

### C2 — Endpoint behavior: document the import history endpoint

**Anchor:** in the *Endpoint behavior* list, directly after the summary bullet
(README line 281) and before the paragraph beginning "Activity lists and
summaries accept …" (line 283).

**Action:** insert this bullet:

```
- `GET /api/emissions/imports/`: import history. This is a backend endpoint
  only — the emissions page has an *Import CSV* dialog but no history view. It
  returns the company's import attempts, latest first, capped at the most
  recent 100 (a plain list, no page parameter). Each item has `id`,
  `original_name`, `outcome` (`success`, `rejected` or `failed`), `row_count`,
  `accepted_count`, `rejected_count`, `created_count`, `error_messages` (a
  list) and `created_at`. Stored file paths are never included. Any
  organisation member can read it, viewers included; unauthenticated requests
  get HTTP 401. Counters are explained under **CSV import** below.
```

**Verified:** `backend/emissions/views.py` (`ImportHistoryView`, lines
196–216: org filter, `[:100]` slice, exact field set without `stored_file`);
permission `IsOrganisationMember` (`backend/accounts/permissions.py` line 9:
any authenticated user with an organisation — viewers included); ordering
`["-created_at", "-id"]` on `ImportLog.Meta` (`backend/emissions/models.py`
lines 103–104); no history UI (`frontend/pages/emissions.py` has an import
dialog only); 401 and latest-first order and field set pinned by
`backend/emissions/tests/test_import_history.py`.

### C3 — CSV import: exact response shape and counter semantics

**Anchor:** *CSV import* section, README lines 298–310. Two changes.

**Action 1** — replace the sentence "The response reports how many records were
created." (line 280, inside the bullet for
`POST /api/emissions/activities/import/`) with:

```
  Success returns `201 {"created": N, "unit": "kg CO2e"}`, where `N` is the
  number of persisted records; a rejected batch returns
  `400 {"file": ["Row <line>: <message>", ...]}`.
```

**Action 2** — append this paragraph at the end of the *CSV import* section,
directly after "A template is available from the import dialog." (line 310):

```
Every upload that passes the request checks (a file is present, it is at most
5 MB, and it decodes as UTF-8) is recorded in an import log, visible at
`GET /api/emissions/imports/`. Requests failing those checks create no history
entry. The log's counters mean: `created_count` is the number of persisted
records and `accepted_count` always equals it (two fields, one value);
`rejected_count` counts rejected rows, not messages — a row with several
validation errors is counted once, and a file-level problem (empty file,
missing column, invalid CSV) is labelled as row 1 and counts as one row;
`row_count` equals `created_count + rejected_count`. On a successful import
this is the number of persisted rows. Two limitations to know when reading
history: in a rejected batch the valid rows are not counted anywhere, so
`row_count` is not "rows examined"; and after an internal storage or database
failure the counters stay 0 (unknown, not guessed) with a generic message, so
internal error details never leak into history. Successful and rejected
attempts keep the stored CSV; there is no download endpoint, and no retention
period has been decided yet. Details and edge cases:
[docs/emissions-import-contract.md](docs/emissions-import-contract.md).
```

**Verified:** response shapes `backend/emissions/views.py` lines 193 and 183–192
(`201 {"created", "unit"}`; `400 {"file": [...]}` capped at 100 messages plus
the "…and N more errors." suffix); counters `backend/emissions/services.py`
`persist_import` lines 177–198 (`rejected_rows = len({error["row"] ...})`,
`row_count = created + rejected_rows`, `accepted_count = created =
created_count`); file-level errors labelled row 1 in
`backend/emissions/csv_import.py` (`parse()` lines 63–71, 97–98, 100–101);
storage/database failure paths lines 170–175 and 199–216 (fixed safe messages,
counters rolled back to 0, stored file deleted on database failure); no
download endpoint exists (contract `docs/emissions-import-contract.md`,
"Scope guard" and history section); retention undecided (contract, open issue
1). The worked example in the contract (2 valid + 1 invalid row →
`row_count = 1`, `rejected_count = 1`, `created_count = 0`) is pinned by
`test_import_history.py::test_success_rejected_and_failed_outcomes_appear`, and
the header-only case by
`test_import_history.py::test_header_only_file_is_rejected_with_its_own_counters`.

**Consistency note:** the existing claims kept unchanged in this section were
re-verified as accurate: all-or-nothing saving, 5 MB / 5,000-row limits, one
audit entry per imported record, no duplicate check, line-number errors, and
the template download (the dialog's "Download template" button,
`frontend/pages/emissions.py` lines 447–451).

### C4 — New subsection: seeding official factors

**Anchor:** new `###` subsection at the end of the emissions block, directly
after the paragraph inserted by C3 and before the `## Hometask 2: Stream
processing` heading (README line 312).

**Action:** insert:

````
### Seeding official factors

The emissions subsystem ships a small reviewed subset of the UK Government GHG
conversion factors 2025: two butane combustion entries (Scope 1). Seed them
into one existing organisation:

```bash
python backend/manage.py seed_official_factors --organisation-id <ID>
```

Replace `<ID>` with the organisation's numeric primary key, visible in the
Django admin or in the `id` field of `GET /api/accounts/organisation/`. Inside
Compose, run the same command with
`docker compose exec backend python manage.py seed_official_factors --organisation-id <ID>`.
The command is explicit and idempotent: factors are stored under
unit-labelled names — `Butane (tonnes)` and `Butane (litres)` — so same-year
factors with different units never share a stored name, and CSV files must
reference these stored names (`factor_year` 2025 is optional). An identical
rerun skips the factors; a conflicting factor with the same name and year
aborts the run without changing anything. Seeding writes no audit history, and
seeded factors are ordinary company factors, not flagged as demo. Provenance,
workbook evidence and the deliberately small coverage:
[docs/emission-factor-sources.md](docs/emission-factor-sources.md).
````

**Verified:** command and required `--organisation-id`
(`backend/emissions/management/commands/seed_official_factors.py` lines 17–31;
parser pinned by
`test_seed_official_factors.py::test_documented_invocation_matches_command_parser`
— see `docs/emission-factor-sources.md` "Seeding into an organisation");
unit-labelled stored names from `f"{entry['name']} ({entry['unit']})"` (seed
command line 37) and `persisted_names` in
`backend/emissions/data/official_factors.json` (`Butane (tonnes)`,
`Butane (litres)`); skip/conflict/abort behavior lines 44–64 and the sources
doc's test summary (10 passing tests, recorded evidence, not re-run here);
`is_demo: False` (seed command line 40); dataset source "UK Government GHG
Conversion Factors for Company Reporting 2025"; UBA explicitly *not* included
(sources doc, "Limits").

**Do not** imply UBA or DEFRA coverage anywhere in the README: the verified
dataset contains exactly the two butane factors, and the UBA part of the
proposal's factor sources is an explicit unverified gap
(`docs/emission-factor-sources.md`, "Limits").

### C5 — Summary bullet: counts respect the filters

**Anchor:** README line 281:

```
- `GET /api/emissions/summary/`: record count, demo count, total and scope totals.
```

**Action:** replace with:

```
- `GET /api/emissions/summary/`: record count, demo count, total and scope
  totals for the filtered window. `count` and `demo_count` respect the same
  `start`/`end`/`scope`/`site` filters as the lists, so a filter with no
  matches returns counts of 0, never an error.
```

**Verified:** `backend/emissions/views.py` `SummaryView` lines 228–242
(`records = filtered_activities(request)`, `count = records.count()`,
`demo_count = records.filter(is_demo=True).count()`); filter validation
`backend/emissions/serializers.py` `ActivityFilterSerializer` (end must be
after start, end exclusive); empty-window behavior pinned by
`test_emissions.py::test_summary_shape_units_and_empty_scope` (cited in
`docs/emissions-totals-api.md`).

### C6 — Recalculate bullet: response and audit nuance

**Anchor:** README lines 259–263 (the bullet for
`POST /api/emissions/factors/<id>/recalculate/`).

**Action:** replace the two middle sentences ("Send the latest GET factor
object … in the audit log.") with:

```
  Send the latest GET factor object as `{"factor": {...}}`; stale
  confirmations return HTTP 409, and success returns `{"updated": N}`, where
  `N` is the number of records whose stored values actually changed. The
  operation is atomic; audit entries with before/after snapshots are written
  only for the records that changed. Snapshots store the serializer's
  displayed values (for example `"40.00"`), not raw database numbers.
```

Keep the surrounding sentences unchanged ("explicitly apply the current factor
to all linked company activities, across all dates/sites", "Admins/editors can
update and recalculate; viewers cannot. Factor deletion is not exposed."), and
keep the last paragraph of the section (README lines 294–296) as is — it is
accurate.

**Verified:** stale check and response `backend/emissions/views.py` lines
58–74 (`{"updated": updated}`); per-record audit only when `before != after`
and `reason: "factor_recalculation"` with serializer-representation snapshots
(`backend/emissions/services.py` `recalculate_factor_records` lines 70–109,
docstring lines 73–83 states the snapshot-string limitation explicitly).

### C7 — First emissions workflow: a seeded-factor demo row

**Anchor:** *First emissions workflow*, directly after the demo paragraph
ending "keep demo activity separate from real company data." (README line 252).

**Action:** insert:

```
With the official factors seeded (see *Seeding official factors* below), a
row such as `2026-01-31,Butane demo,Main office,Butane (tonnes),2025,0.5,tonnes`
saves as **1516.69 kg CO2e** (0.5 t × 3033.38067 kg/t, rounded half up to
0.01 kg). The site name must match one of your company's sites exactly. Seeded
factors are not flagged as demo, so records calculated with them count as
ordinary company data — work in a separate organisation if you are only
exploring. The 100 kWh × 0.4 = 40.00 kg CO2e example above uses the synthetic
demo factor and *is* flagged.
```

**Verified:** calculation 0.5 × 3033.38067 = 1516.690335 →
`quantize(0.01, ROUND_HALF_UP)` = 1516.69
(`backend/emissions/calculations.py` `CO2eCalculator.calculate` lines 37–46);
exact unit match required (line 39); factor name/year lookup from the stored
name (`backend/emissions/csv_import.py` `_match_factor` lines 198–214);
`is_demo` copied from the factor at save time
(`backend/emissions/services.py` `create_activity` line 35); CSV column order
matches the template in `frontend/pages/emissions.py` lines 14–17. The demo
factor example itself (README lines 246–252) is unchanged and remains
accurate, including the 40.00 kg CO2e result.

---

## 3. Flags for D07, D08 and the parent

These are findings from reading; nothing here was changed in code or README.

1. **Package markers are untracked, but command discovery is not shown broken.**
   `backend/emissions/management/__init__.py` and
   `backend/emissions/management/commands/__init__.py` are empty and untracked.
   D03's Django 5.2 source analysis and isolated namespace-package probe show
   discovery and loading work without them. Include both in the D10 handoff
   for explicit packaging; do not claim an unknown-command failure or a
   verified fresh-clone run. See `docs/emissions-delivery-evidence.md`, section 4.
2. **`dev.md` row A11 (import-history UI) is superseded and deferred.** The
   delivery plan defers any import-history UI. The README wording proposed
   here states the endpoint is backend-only and does not promise a UI. Do not
   copy dev.md rows A11–A12 or the "small company-scoped import history view"
   item into the README.
3. **Deferred items must not be implied as existing or coming:** no stored-file
   download endpoint (contract, A10 scope), no UBA/DEFRA factor expansion (two
   butane factors only), no retention/pruning decision (nothing is deleted
   except the DB-failure file cleanup), no KIConnect or production deployment
   claim (absent from the README already — keep it that way).
4. **Evidence freshness.** The README currently makes no test-count or
   coverage claim; keep it that way unless evidence is refreshed. Recorded
   evidence per the delivery plan: 271 tests passed, Django check and Ruff
   passing (recorded run at `97c11b5`, as attributed in D03); the appendices in
   `docs/emissions-verification.md` pin 222 then 240 passing at earlier
   revisions, plus 94% emissions coverage and the ~1.4 s / 5,000-row benchmark
   as earlier SQLite results. If the final code revision changes before
   submission, that evidence needs a refresh per the plan.
5. **The benchmark script is tracked.** Parent reconciliation verified
   `git ls-files scripts/measure_import_5000.py`; D03 records its inclusion in
   commit `9627686`. A08's older untracked statement is historical and must
   not prevent linking the script. Its measurements remain older SQLite evidence.
6. **README claims checked and found accurate — no correction needed.** Listed
   so reviewers do not re-audit them: "Activity lists and summaries accept
   `start` (inclusive), `end` (exclusive), `scope` (1–3), and `site`"; "Lists
   use 20 records per page and accept `page`"; invalid filters → 400; quantity
   ≤ 4 decimals / factors ≤ 8; rounding half up to 0.01 kg once per record;
   edits keep the saved factor version; deletion keeps audit details; the
   "Correcting a factor" section (README lines 639–646); the Compose claim
   "starts PostgreSQL, applies Django migrations, and starts the backend and
   frontend" (three services `db`/`backend`/`frontend`, backend command runs
   `migrate --noinput`; `compose.yaml` lines 34–36).
7. **`accepted_count` vs `created_count` is not a meaningful distinction** —
   both always hold the same value (contract: the proposed distinction was
   dropped at implementation). C3 words this as "two fields, one value"; D07
   should not present them as different concepts.

## 4. Checks performed in this task

- Read the README end to end; compared every emissions claim (lines 187–310,
  639–646) against the implementation.
- Read `backend/emissions/`: `models.py`, `views.py`, `urls.py`, `services.py`,
  `serializers.py`, `calculations.py`, `csv_import.py`,
  `management/commands/seed_official_factors.py`, `data/official_factors.json`.
- Read tests that pin the documented behavior:
  `test_import_history.py`, `test_seed_official_factors.py` (grep of the
  usage-pinning test).
- Read the companion docs for links and consistency:
  `docs/emissions-import-contract.md`, `docs/emissions-totals-api.md`,
  `docs/emission-factor-sources.md`, `docs/emissions-verification.md`. All four
  exist; the links proposed in C3/C4 resolve to them from the repository root.
- Read `compose.yaml`, `backend/config/urls.py`,
  `frontend/pages/emissions.py` (import dialog, CSV template, no history UI)
  and `backend/accounts/permissions.py`.
- Checked git state (branch `feature/emissions-import-history` at `97c11b5`;
  two untracked package markers; measurement script confirmed tracked during
  parent reconciliation).
- Confirmed the worked example's arithmetic (1516.69 kg CO2e) against the
  calculator's rounding rule.

Not done (per plan: documentation-only task): no test rerun, no Django check,
no Ruff run, no README or code edit, no commit.

## 5. Open questions for the parent

1. Should the README mention the untracked package markers as a caveat (C4),
   or is committing them in the delivery commit sufficient? Prefer committing
   them and keeping the README clean.
2. C1–C7 are emissions-only corrections. D07 owns integrating them with D03's
   evidence wording and D05's rendered diagram; no conflicts are expected, but
   C2's "Counters are explained under **CSV import** below" depends on C3
   being applied in the same edit — apply both or neither.
