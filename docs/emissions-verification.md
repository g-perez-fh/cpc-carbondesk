# Emissions verification — current state before repairs

Recorded 10 November 2026 while inspecting the partial import-history work
(dev.md row A01). This document is evidence of the *current* diff, not a
baseline report: the earlier "Django check, 217 tests, Ruff passing" claim was
made before the pending edits and no longer describes this worktree.
No code was changed while producing this report; the only file written is this
one.

## Environment and revision

| Item | Value |
| --- | --- |
| Git revision | `e81f3f8a22581c0e2cce97303d31961faeebac51` ("Update Guillermo Pérez Pérez's matriculation number"), branch `main` |
| Interpreter | `.venv/bin/python`, Python 3.13.12 (bare `python` is not available in the shell) |
| Database engine | `DB_ENGINE=sqlite` (from `.env`); Django test runs use the automatic isolated test database, verified below |
| File storage | `MEDIA_ROOT = backend/media`, `MEDIA_URL = media/` (`backend/config/settings.py`); the directory was empty before and after the test run |
| Docker/PostgreSQL | Not used in this row; no container or PostgreSQL dependency was exercised |

## Changed files in the worktree

Tracked modifications (from `git diff --stat`, 4 files, +107/−10):

| File | Change |
| --- | --- |
| `backend/emissions/models.py` | New `ImportLog` model (organisation, actor, original name, stored file, outcome `success`/`rejected`/`failed`, `row_count`/`accepted_count`/`rejected_count`/`created_count`, `error_messages` JSON, `created_at`). Deliberately unverified for correctness in this row. |
| `backend/emissions/services.py` | New `persist_import(...)` alongside the existing `import_activities(...)`. Contains the known defects below. |
| `backend/emissions/views.py` | Import endpoint now calls `persist_import` inside a broad `except Exception → HTTP 500`; new `ImportHistoryView`. |
| `backend/emissions/urls.py` | New route `emissions/imports/` → `ImportHistoryView`. |

Related untracked files (user/agent work, not modified):

- `backend/emissions/migrations/0003_importlog.py` — migration for `ImportLog`.
- `backend/emissions/management/commands/seed_official_factors.py` and
  `backend/emissions/data/official_factors.json` — factor seeding work owned by
  the other agent/R2; not inspected for correctness here beyond what the lint
  run reported.
- `docs/emission-factor-sources.md` — factor provenance, factor-row owner.

## Required checks (actual results)

All commands ran from the project root using `.venv/bin/python`.

### 1. `backend/manage.py check` — PASS

```
System check identified no issues (0 silenced).
```

A related read-only confirmation, `backend/manage.py makemigrations
--check --dry-run`, reported `No changes detected`: no model drift beyond the
pending `0003_importlog.py` migration. (Independent reviewer confirms the same.)

Note that `check` does not import the broken code path at runtime — see the
failing tests below. Passing `check` is not evidence the import flow works.

### 2. `python -m pytest` — 17 FAILED, 200 PASSED (out of 217)

Isolation used and verified:

- `DB_ENGINE=sqlite`, so the test runner creates its own test database and
  destroys it afterwards ("Destroying test database for alias 'default'" in the
  log). The development database `backend/db.sqlite3` was not opened with
  `manage.py` at any point and shows no modification in `git status`.
- No test writes to file storage in the current suite (no test file references
  `persist_import`, `ImportLog`, `default_storage` or `MEDIA_ROOT`), and
  `backend/media` contained 0 files before and 0 files after the run. Upload
  storage behavior is therefore not covered by any test yet; A05+ must not rely
  on this and should run with temporary storage.

Failures — all 17 are emissions CSV import tests hitting the changed endpoint,
i.e. the partial edits, not unrelated team code:

```
FAILED backend/emissions/tests/test_csv_import.py::test_valid_csv_imports_and_calculates
FAILED backend/emissions/tests/test_csv_import.py::test_trailing_zeros_are_accepted
FAILED backend/emissions/tests/test_csv_import.py::test_import_is_limited_to_5000_rows
FAILED backend/emissions/tests/test_csv_import.py::test_error_list_is_capped
FAILED backend/emissions/tests/test_csv_import.py::test_missing_columns_are_reported
FAILED backend/emissions/tests/test_csv_import.py::test_malformed_row_reports_line_number_and_writes_nothing
FAILED backend/emissions/tests/test_csv_import.py::test_unknown_site_and_factor_are_reported
FAILED backend/emissions/tests/test_csv_import.py::test_unit_must_match_the_factor
FAILED backend/emissions/tests/test_csv_import.py::test_factor_year_disambiguates_versions
FAILED backend/emissions/tests/test_csv_import.py::test_other_company_names_are_not_visible
FAILED backend/emissions/tests/test_csv_import.py::test_header_is_normalised_and_blank_rows_are_skipped
FAILED backend/emissions/tests/test_csv_import.py::test_empty_file_is_rejected
FAILED backend/emissions/tests/test_csv_import.py::test_invalid_values_are_reported[future]
FAILED backend/emissions/tests/test_csv_import.py::test_invalid_values_are_reported[negative]
FAILED backend/emissions/tests/test_csv_import.py::test_invalid_values_are_reported[four-decimal-precision]
FAILED backend/emissions/tests/test_departments.py::test_csv_department_is_company_scoped[Engineering-201]
FAILED backend/emissions/tests/test_departments.py::test_csv_department_is_company_scoped[Foreign-400]
```

(reviewer-confirmed variant of the last two listed as CSV + department suites:
17 failed / 7 passed across those two files)

Representative failure: `test_valid_csv_imports_and_calculates` expects HTTP
201 but receives `500 {"file": ["The import could not be saved. No activities
were created."]}`. Rejection tests that expect HTTP 400 receive the same 500.
`test_departments.py` shows the same pattern in both parametrize cases: a valid
department import that should return 201 and a foreign-department import that
should return 400 both return 500 instead. CSV+department suites combined:
17 failed / 7 passed (reviewer-confirmed count).

### 3. `python -m ruff check .` — 9 errors (no fixes applied)

All 9 findings are in the emissions app and match the known partial edits:

| Finding | Location | Meaning |
| --- | --- | --- |
| `F821 Undefined name StorageError` | `services.py:110` | `storage_errors = (OSError, StorageError)` references a name that is never defined or imported. |
| `F821 Undefined name StorageError` | `services.py:126` | `except (OSError, StorageError) as exc:` in `persist_import` — evaluated when the function *runs*, not at module import, which is why `check` passes but every import request fails. Raising `NameError` inside `except` clause evaluation stops the whole request. |
| `F401 Storage imported but unused` | `services.py:108` | Leftover import next to `default_storage`. |
| `F841 storage_errors assigned but never used` | `services.py:110` | The tuple itself is dead code even if the name were defined. |
| `F401 ActivityRecord imported but unused` | `management/commands/seed_official_factors.py:11` | In the other agent's seed command file. |
| `I001` unsorted/import block | `services.py:107`, `urls.py:1` | Formatting-level; tidy-up only. |
| `E501 line too long` | `urls.py:4` (112 chars), `views.py:191` (113 chars) | The 500-handler line and the view import line. |

4 of the 9 findings are auto-fixable; none were fixed in this row per the plan.

### 4. `python -m ruff format --check .` — 4 files would be reformatted (no changes applied)

```
unformatted: backend/emissions/management/commands/seed_official_factors.py
unformatted: backend/emissions/migrations/0003_importlog.py
unformatted: backend/emissions/urls.py
unformatted: backend/emissions/views.py
113 files already formatted
```

Matches the reviewer's independent count of 4 files. No file was reformatted.

## Confirmed defects (for A02+ to fix in separate rows)

1. **Undefined `StorageError` → `NameError` at execution time.** Confirmed
   independently by the reviewer ("directly confirmed `NameError` on
   `persist_import` invocation") and visible in this row purely through the
   effect: every test that reaches the import endpoint gets the blanket 500
   response because `views.py:190`'s broad `except Exception` catches the
   `NameError` raised while evaluating the `except (OSError, StorageError)`
   tuple, and hides the programming error behind HTTP 500. Even a valid file
   that should create activities returns 500. This is the first thing A02
   should narrow.
2. **Row counts are wrong, not just unavailable.** In `persist_import`,
   `row_count = created + len(errors)` and `rejected_count = len(errors)` count
   *error messages*, not rejected *rows*. A row with several validation errors
   is counted once per message (`CsvImporter.parse()` may report more than one
   error per row). Successful-import totals also double-count `accepted_count`
   vs `created_count` (both set to the same value). Needs a documented
   contract (A03) before fixing.
3. **Database-failure path is dubious.** In the `except DatabaseError` branch:
   it stores raw `exc` text in `ImportLog.error_messages` (sensitive exception
   details recorded into a log that a later history endpoint will expose),
   calls `log.save()` when the database may be unusable, and relies on
   `transaction.atomic` semantics across `import_activities` calls that each
   open their *own* atomic block — so a midway failure does not necessarily
   roll back the whole batch. Also untested: whether the stored upload file is
   actually removed (filesystem writes are not rolled back by DB
   transactions), and what happens when `default_storage.delete` itself fails.
4. **History endpoint is not yet protected/specified end-to-end.**
   `ImportHistoryView` is org-filtered and capped at 100 records, which is a
   reasonable start (reviewer agrees current filter/membership look sound), but
   it has no explicit viewer-role policy, no pagination beyond the hard `[:100]`
   slice, does not return `created_at` in a stable format, and its tests do not
   exist yet. `stored_file` is correctly *not* in the response.
5. **Storage privacy is not yet an access-control question, but is also not
   proven safe.** No public media-serving URL route exists in
   `backend/config/urls.py` (only admin/api include paths), so no demonstrated leak
   path exists today — reviewer's position, which I verified by reading
   `backend/config/urls.py`. The `private/…` naming is convention only; this stays
   open for A05, which must inspect the actual serving configuration (gunicorn,
   docker volumes, future `MEDIA_URL` exposure).
6. **Migration `0003_importlog.py` is syntactically consistent** (`makemigrations
   --check --dry-run` passes), but it has never been applied to the real
   development database and no migration test exists. Whether the fields fit
   the import contract is deferred to A04, not asserted here.

## What is deliberately NOT in this row

- No code edits, no `ruff --fix`, no format, no migration changes.
- No claim about the 217 tests pre-edit (that suite is not current evidence).
- No verification of `seed_official_factors.py` correctness or the factor
  data files (factor-row ownership).
- No browser/history UI checks — the history UI does not exist yet (A11).
- Performance (5,000 rows < 10 s) and coverage (≥ 80 %) measurements are
  separate rows (A15–A18) and were not attempted.

## Handoff to A02

Contract the next implementer must satisfy:

- Remove/repair the undefined names: define or import `StorageError` (or drop
  it deliberately and justify), drop the unused `Storage` import and unused
  `storage_errors` variable, sort the affected import blocks.
- Replace or narrow the `except Exception` in `views.py:190` so that a genuine
  programming error (`NameError`) cannot silently become HTTP 500; regression
  test must demonstrate the previous failure mode is gone, e.g. an import that
  previously hit the blanket 500 now behaves as documented.
- Do not change `ImportLog` fields or the migration in A02 itself; that is A04.
- Keep `backend/media` free of test artifacts: use temporary storage overrides
  for any test that exercises file writing (A05+), not the real `MEDIA_ROOT`.

Checks to re-run after A02, with expected budgets:

- `backend/manage.py check` — still 0 issues.
- focused emissions tests — the 17 CSV/department failures above are the
  regression baseline; the repair should bring them back towards pass *without*
  hiding other failures.
- `ruff check` on touched files — 0 findings on those files
  (other 1 F401 in seed command belongs to the factor agent's row).
- `ruff format --check` on touched files — reformatted or untouched, but not
  left half-formatted.

## A02 — undefined names repaired, endpoint catch narrowed (10 November 2026)

Scope guard: only `backend/emissions/services.py`, `backend/emissions/views.py`,
the new `backend/emissions/tests/test_import_error_paths.py`, and this appendix
were written. No row-count, retention, transaction-design or UI fix was
attempted (later rows own those); no other agent's file was touched.

### Changes to `services.py`

- Removed the undefined `StorageError` references (`F821` at the old lines 110
  and 126), the unused `Storage` import (`F401`) and the unused
  `storage_errors` tuple (`F841`); moved `default_storage` to a module-level
  import so all import/test runs patch the same object the function uses.
  `persist_import` now catches the exception that the project's configured
  local `FileSystemStorage` (the default storage) actually raises on a failed
  save: `OSError`.
- The `persist_import` docstring now documents exactly what it raises
  (`OSError` on storage failure, `DatabaseError` on database failure) and both
  are still re-raised to the caller after the attempt is recorded in
  `ImportLog`. No count/retention/rollback logic was altered.

### Changes to `views.py`

- The import endpoint's `except Exception:` was narrowed to
  `except (OSError, DatabaseError):` — the two documented expected failures of
  `persist_import`. A genuine programming error (e.g. `NameError`, which this
  very endpoint used to hide behind HTTP 500) now propagates instead of being
  turned into the misleading "could not be saved" response. The response body
  and `status=500` exist only for those expected failures and were kept
  byte-for-byte; the success (`201 {"created": ..., "unit": "kg CO2e"}`) and
  validation (`400 {"file": [...]}`) shapes are unchanged and covered by the
  untouched existing tests.
- `views.py` was reformatted with `ruff format` (it was one of the four files
  failing the A01 format check and belongs in A02's file list); formatting
  changes are mechanical except the narrowed catch block.

### New focused test file `backend/emissions/tests/test_import_error_paths.py`

Four tests, each isolating upload storage through a fresh `FileSystemStorage`
rooted in the test's temporary directory (`isolated_storage` autouse fixture),
so the real `backend/media` cannot receive files even when the file is run on
its own:

1. `test_success_stores_file_with_generated_name` — valid CSV → 201; the
   stored path is generated (`private/emissions-imports/<org>/<uuid>.csv`),
   the client's file name (`company-realname.csv`) never appears in the path.
   (Field details/retention stay with later rows.)
2. `test_programming_errors_are_not_swallowed` — `persist_import` monkeypatched
   to raise `RuntimeError`; the test asserts the exception propagates out of
   the request instead of becoming the generic HTTP 500 file response.
3. `test_storage_failure_returns_documented_response_and_logs_attempt` —
   storage save patched to raise `OSError` → 500 with the documented body, an
   `ImportLog` with outcome `failed`, and no activities.
4. `test_database_failure_deletes_file_and_records_failed_attempt` — patched
   `import_activities` raises `DatabaseError` → same documented 500, failed
   log, stored file deleted, no activities.
   (The DB-failure *handler internals* remain as-is on purpose; A09 owns them.)

One test needed a retry during the run: the storage-failure test initially
patched `django.core.files.storage.default_storage.save` while the service was
looking up its own module binding replaced by the fixture — it got the parsing
`400` instead of the storage `500`. Patching the service module reference
instead corrected this; the fix is in the delivered file.

### Check results (all with `.venv/bin/python` from the project root)

| Check | Command | Result |
| --- | --- | --- |
| Touched-file lint | `ruff check backend/emissions/services.py backend/emissions/views.py backend/emissions/tests/test_import_error_paths.py` | **All checks passed** |
| Touched-file format | `ruff format --check` (same three) | 3 files already formatted |
| Full Django check | `backend/manage.py check` | 0 issues |
| Focused regression | `pytest backend/emissions/tests/test_import_error_paths.py --ds carbondesk_temp_settings` | 4 passed |
| Restored paths | `pytest backend/emissions/tests/test_csv_import.py backend/emissions/tests/test_departments.py --ds carbondesk_temp_settings` | 24 passed (all 17 A01 failures back to green) |
| Full suite | `pytest --ds carbondesk_temp_settings` | **222 passed** (217 pre-edit count + 4 new A02 tests + 1 test in the factored agent's new `test_seed_official_factors.py`) |
| Project lint | `ruff check .` | **2 errors remain, both in `urls.py`** (`I001` unsorted import block, `E501` over-long view import line) — `urls.py` is not in A02's allowed file list; it goes to the row that next touches it (A10). The seed-command `F401` from A01 was fixed concurrently by the factor agent in its own file. |
| Project format | `ruff format --check .` | touched files clean; `urls.py` and the parallel migration/seed files remain unformatted (not A02 files) |

### Test-media isolation

`MEDIA_ROOT` is isolated two ways during this row's verification:

- **Process level (all pytest runs):** a temporary settings module
  `carbondesk_temp_settings.py` in `/tmp/opencode` imports `config.settings`
  and overrides `MEDIA_ROOT` to a fresh `mkdtemp` directory; pytest ran with
  `PYTHONPATH=/tmp/opencode pytest ... --ds carbondesk_temp_settings`. This
  protects the pre-existing CSV/department suites, which call the import
  endpoint and now write real upload files.
- **Test level (new file, durable):** the `isolated_storage` autouse fixture
  injects a throwaway `FileSystemStorage` into `emissions.services`, so the
  new file isolates itself even in a plain run without the wrapper.

Evidence the isolation is real, not accidental: uploads landed under
`/tmp/carbondesk-test-media-*/private/emissions-imports/1/<uuid>.csv` with
generated UUID names; `backend/media` contained 0 files before and after every
run; the last two temp roots are intentionally left in `/tmp` for inspection.

Known gap honestly recorded: in a plain `pytest` run without the temporary
settings module, the *pre-existing* CSV/department suites would write upload
files into the real `backend/media` (no test there covers storage yet). A
shared durable fixture belongs to conftest, which is outside A02's allowed
files, and is deferred to the storage row (A05) where the actual media-serving
configuration is being inspected.

### Concurrency note

`backend/emissions/tests/test_seed_official_factors.py` appeared in the
worktree during this row (factor agent B's scope). It was not read, not run and
not modified here beyond the full-suite fact that its single test passed in the
shared run. Its `F401` lint finding from A01 is gone.

## A08 — Stage 5 verification measurements (10 November 2026)

Evidence row, docs-only: no production code was written; the only repo files
touched were this document, `requirements-dev.txt` (one dependency pin) and the
new measurement script noted below.

### Import performance: 5,000-row target (plan.md Stage 5)

Measured with the **real web import flow**: a multipart POST to
`POST /api/emissions/activities/import/` through
`rest_framework.test.APIClient`, so the measurement includes the view preflight,
the storage write, parsing, the all-or-nothing save and the per-record audit
entries (`persist_import` internals are exercised, not bypassed).

Synthetic demo data only (description prefix `Demo import row N`, factor source
"Synthetic measurement example", `is_demo=True` factor), matching the demo
conventions used in the tests. Each run used a fresh disposable SQLite database
and a throwaway media directory in `/tmp`; `backend/db.sqlite3` and
`backend/media` were untouched (storage 0 files). Wall time via
`time.perf_counter`; single run plus one repeat per scenario, per plan.

| Scenario | Run 1 | Run 2 | HTTP | Log outcome / counters |
| --- | --- | --- | --- | --- |
| 5,000 valid rows | 1.43 s | 1.45 s | 201 | `success`, `row_count = 5000`, `rejected_count = 0`; 5,000 records + 5,000 CREATE audits |
| 5,000 rows, every 3rd row invalid (`unit "W"`) | 0.08 s | 0.08 s | 400 | `rejected`, `row_count = 1666` unique rejected rows, 0 created; message list capped at 100 |

**Result: the under-10 s target is met on this setup** (1.43–1.45 s ≈ 15 % of
budget).

**Honest caveats — one-setup evidence, not portable guarantees:**

- Measured on one machine, one Python process, against SQLite; the shared
  network-mounted workspace and the container target (PostgreSQL/per-executor)
  can behave differently.
- The 10-second target comes from the project proposal speaker notes; this
  measurement is our verification of it on this setup, not new professor
  requirements.
- The error path is cheap (0.08 s) **because validation itself is cheap and
  nothing persists** in a rejected batch (all-or-nothing): the dominant cost on
  the valid path is persisting 5,000 records plus their audit rows, not
  parsing.
- Deliberately **not** added as a routine pytest test: wall-clock targets are
  nondeterministic. Numbers live in this section and in the script output.

**Script:** `scripts/measure_import_5000.py` (self-contained disposable
settings; run `.venv/bin/python scripts/measure_import_5000.py` from the repo
root). Note: `scripts/` is currently **untracked** in git; the script is
recorded in the worktree and this report only, nothing committed or pushed.

### Coverage: emissions app (plan.md Stage 5, ≥ 80 %)

Command (explicit, not wired into default runs or CI):

```
.venv/bin/python -m pytest -q --cov=emissions --cov-report=term-missing
```

Result with the full suite passing in the same run (`240 passed`, 20.4 s):
**backend/emissions total 94 % — 707 statements, 40 missed.** Exceeds the 80 %
target on this setup (SQLite).

**Scope definition (agreed within the emissions work, subject to team
confirmation — not a professor requirement):** `--cov=emissions`, i.e. the
`backend/emissions` package only, is the agreed default for the emissions
subsystem's Stage-5 coverage claim; each subsystem owner reports their own app,
and a whole-backend claim is a later team decision.

Supporting dependency: `pytest-cov==7.1.0` pinned in
`requirements-dev.txt` with a one-line comment; coverage runs stay an explicit
command.

**Top uncovered spots — reported, not chased in this row:**

| File | Coverage | Missing |
| --- | --- | --- |
| `backend/emissions/csv_import.py` | 85 % | 24 lines of individual validation branches: duplicate-header returns (67, 108), extra-values/blank-row skips (87–92, 114), `csv.Error` file path (97–98), required-field/cap messages (128–135, 162), row-calculation error path (`except EmissionsError`, 171–172), site/factor/quantity validation messages (190–227) |
| `backend/emissions/calculations.py` | 88 % | 17, 31–32, 45 — invalid-input raises (unit required, invalid number, result too large) |
| `backend/emissions/services.py` | 95 % | 21, 50 (organisation-mismatch raises), 98–99 (recalculation error re-raise with the record label), 211–215 (nested `DatabaseError` fallback when the failure-log save itself fails) |
| `backend/emissions/views.py` | 98 % | 73 (recalculate error mapping), 162 (oversize-file preflight response) |
| `serializers.py` / `models.py` / `streaming.py` | 98–99 % | 76–77 / 107 / 51 — single validation/internals lines |

Per instructions from the parent, uncovered lines were recorded only; closing
them was explicitly out of scope for this row.

### Gate reruns at the A08 boundary

| Check | Result |
| --- | --- |
| Full suite (plain) | `240 passed` (19.13 s) |
| `ruff check .` | All checks passed (including the new script) |
| `ruff format --check .` | clean, including `scripts/measure_import_5000.py` |
| `backend/manage.py check` | 0 issues |
| `backend/media` before/after | 0 files |

