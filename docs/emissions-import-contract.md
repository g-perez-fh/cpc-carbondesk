# Import contract — CSV activity imports

Status: **implemented baseline**, reconciled with the code in the
contract-documentation pass (10 November 2026). It defines what the import
endpoint and its history do; the tables mark where current code already
behaves this way and where later rows must still change it. This document is an engineering agreement between the A-step tasks, not a
professor requirement. It deliberately stays small: four documented outcomes,
explicit counting rules, no framework and no state machine beyond the
`success`/`rejected`/`failed` outcome labels that already exist on `ImportLog`.

Scope guard: everything here concerns the emissions CSV import
(`POST /api/emissions/activities/import/`) and the import history
(`GET /api/emissions/imports/`). File download endpoints do not exist yet; if
they are added, their own access rules belong to A10.

## Separation of levels

| Level | Owner row | What it decides |
| --- | --- | --- |
| Preflight | view (implemented) | Is there a file, is it ≤ 5 MB, is it UTF-8? |
| Parse & counts | importer | Are the header and rows valid? Errors carry CSV line numbers; counts are derived in the service. |
| Persistence | service (implemented) | Store file, save activities or roll back, count rows, record the attempt. |
| History | implemented (row A06 tests) | What is returned for the logged attempts. |

The endpoint returns **always exactly one of** the response shapes below and
never invents data. All-or-nothing semantics are kept: activities and their
audit entries are saved through `import_activities` only when **every** data
row passes validation.

 - success: HTTP **201**, body `{"created": N, "unit": "kg CO2e"}`
 - any rejection or failure: HTTP **400** or **500** with body `{"file": [messages...]}`

## Request-level preflight rejections (implemented)

Checked in the view before the service is called and before anything touches
storage or the database:

| Condition | Response | Body (first message) |
| --- | --- | --- |
| No file posted | 400 | `"Choose a CSV file to import."` |
| File larger than 5 MB (`MAX_IMPORT_BYTES`) | 400 | `"The file is larger than 5 MB."` |
| Not decodable as UTF-8 (`utf-8-sig`) | 400 | `"The file must be UTF-8 encoded."` |

**History decision:** these requests do **not** create an `ImportLog` row and
store nothing (implemented). Reason: there is nothing persisted — no
decodable file content is received or stored — and a client-fixable coding
mistake is not company import history. The proposal's import-history scope
(logs for attempted imports) is kept for every request that *passes* these
checks; this exclusion is a deliberate, documented narrowing, not a silent one.
An oversize or non-UTF-8 request therefore never leaves storage residue, and no
filesystem cleanup is needed for it.

## Import execution outcomes

From here on, every attempt is recorded in one `ImportLog` row whose
`outcome` is `success`, `rejected` or `failed`, for example
`"company-realname.csv": "success"`.

### Success (implemented)

File stored, all rows valid → `201 {"created": N, "unit": "kg CO2e"}`;
each accepted row is saved with an activity audit entry inside one atomic
block; the log stores the generated storage reference and the counts below.

### Rejected batch: file-level and row-level errors (implemented)

A response `400 {"file": [...]}` with the file's own error list:

 - **File-level errors** are reported once, labelled as row 1 by the parser:
   empty file ("The file is empty."), duplicate header columns, missing
   required columns, invalid CSV syntax, header-only file ("The file has no
   activity rows."). A header-only file — zero data rows after the header — is
   a *rejection of the uploaded file by contract*, not a success: it creates no
    activities and, see counting rules, its file-level message counts as one
    rejected row (`row_count = 1`, `rejected_count = 1`, `accepted = created = 0`)
    with outcome `rejected`.
 - **Row-level errors**: rows failing any validation (unknown or ambiguous
   site/factor, wrong unit, non-numeric/boundary quantity, future date,
   missing description…) are rejected. One row may produce several messages;
   the rejected *row* is still one row.
 - More than `MAX_ROWS` (5 000) data rows → the batch is rejected with the
   documented "Only the first 5000 rows can be imported." message; nothing is
   imported even if the earlier rows are valid (all-or-nothing).

When *any* row fails, **nothing is saved**: no activities, no audit entries.
The response returns the first `MAX_REPORTED_ERRORS` (100) messages plus, if
there are more, the existing "…and N more errors. Fix these first…" note.
Messages are shown in the same format implemented today:
`"Row {line}: {message}"`. Message text stays user-oriented: it may echo short
CSV cell values (site/factor names) but must never contain storage paths,
traceback text or library exception text (both failure paths follow this; the
fixed safe log messages are pinned verbatim by `test_import_error_paths.py`).

### Storage failure (implemented)

`persist_import` stores the upload under a **generated name** it computes
(`private/emissions-imports/<org>/<random hex>.<safe suffix>`) before parsing.
If storage raises `OSError`:

 - response **500** with the start-of-service body
   `{"file": ["The import could not be saved. No activities were created."]}`
 - an `ImportLog` row with outcome `failed` and `stored_file` empty
 - no activities, no audit entries, no file on disk (nothing was stored)

Per the A02 decision the exception is `OSError` exactly; no retry loop exists
at this level. **Log hygiene (implemented):** the log records the fixed, safe
message `"Upload storage failed: an internal error occurred while saving the
file."` instead of raw `OSError` text, so storage backend details never reach
the history response
(`test_import_error_paths.py::test_storage_failure_returns_documented_response_and_logs_attempt`
pins the response body and this exact message text).

### Database failure (implemented)

If `import_activities` raises `DatabaseError` inside the atomic block:

 - the DB work (activities, audits, log field updates) **rolls back entirely**
 - the *already-stored upload file is deleted* — filesystem writes are not
   rolled back by a database transaction, so cleanup is an explicit service
   step, historically resolved by A02
 - the surviving pre-atomic `ImportLog` row is updated to outcome `failed`
   with `stored_file` empty; no activities remain
 - response **500**, same documented body as above

**Failure-log hygiene (implemented):** the surviving log is updated with the
fixed, safe message
`"Database save failed: an internal error occurred while saving activities."`
instead of `{exc}` text, because database errors can expose internal table and
constraint details through the history endpoint. The cleanup write is guarded:
if refreshing or saving the log fails again, the original `DatabaseError` is
re-raised unchanged. The safe message text is pinned verbatim by
`test_import_error_paths.py::test_database_failure_deletes_file_and_records_failed_attempt`
(also covering the response body, the deleted file and the empty
`stored_file`). One known limit remains: the upload-file delete right after
the rollback is **not** guarded, so a failing delete can mask the database
error (open issue 3).

**Counts note (documented behavior):** after a rolled-back transaction the
success-path count update is rolled back too, so a `failed` log shows
`row_count = accepted = rejected = created = 0` even when the parser had
already produced totals. That is acceptable: they are stored as **unknown**,
never guessed. If a later row wants persisted numbers here, it must handle
DB-side failure safely first.

### Domain invariant (documented assumption)

`EmissionsError` from organisation checks inside `create_activity` cannot occur
through this endpoint because the parser only matches the organisation's own
sites and factors. If it ever reaches the view it propagates as an unhandled
server error — that is deliberate signal, not hidden. A08 must confirm this
assumption while narrowing error handling.

## Counting rules (implemented in `persist_import`, tested)

All counters are derived in the service after parsing, from the number of
saved activities and the parser's flat error list
(`backend/emissions/services.py`):

| Field | Implemented meaning |
| --- | --- |
| `rejected_count` | Data rows with **one or more** validation messages — `len({error["row"] for error in errors})`: grouped by row, counted once per row, never per message. |
| `created_count` | Activity records actually persisted: equals the number of rows saved on success, always `0` when the batch is rejected, rolled back to `0` (unknown) on a database failure. |
| `accepted_count` | Equal to `created_count`, by construction. The originally proposed distinction between "rows that pass validation" and "rows persisted" was dropped when the counters were implemented. |
| `row_count` | `created + rejected_rows`, i.e. `created_count + rejected_count`. On success this is the number of persisted data rows; on a rejected batch the valid-but-unpersisted rows are **not** counted anywhere (limitation below). |
| `outcome` | `success` iff rows were persisted; `rejected` for file or row validation errors; `failed` for storage or database failures. |

**Invariant:** `row_count = created_count + rejected_count` and
`accepted_count = created_count`. No database rule enforces this — `ImportLog`
has no `CHECK` constraints; the rule lives only in `persist_import` and in the
tests that pin its counters, so direct model writes can violate it.

**Known limitation:** for a rejected batch that contains some valid rows,
those rows appear in no counter (`created_count` is `0` by all-or-nothing
semantics and they produced no error), so `row_count` no longer means
"data rows examined". Parsing itself is unaffected; only the persisted log
understates such a file. For preflight rejections and failures counts stay
unknown, reported as `0` and never estimated.

### Worked example (valid2/invalid1, reconciled with the implemented tests)

File with header + 3 data rows: rows 1–2 valid; row 3 carries two violations
(e.g. a bad date and a unit mismatch).

 - parsing: `activities = 2`, flat error list = `[{row: 3, msg...}, {row: 3, msg...}]`
 - log row: outcome `rejected`, **`row_count = 1` (the rejected row only —
   the two valid rows are not counted, see the limitation above),
   `accepted_count = 0`, `rejected_count = 1` (not 2!), `created_count = 0`**
 - HTTP **400**, body `{"file": ["Row 3: Use a date in YYYY-MM-DD format.",
   "Row 3: Unit 'W' does not match the factor unit 'kWh'."]}` (both messages
   from that single row, capped and suffixed exactly as implemented today)
 - DB state: **0 activities, 0 audit rows**, file retained, `created_count = 0`

A success file with the same 2 valid rows (no row 3): outcome `success`,
`row_count = 2`, `accepted_count = 2`, `rejected_count = 0`,
`created_count = 2`, `201`, 2 activities + 2 audit rows.

Both shapes are pinned by
`test_import_history.py::test_success_rejected_and_failed_outcomes_appear`
(success: two imported rows → `accepted_count = created_count = 2`,
`rejected_count = 0`; one invalid row → `row_count = 1`, `rejected_count = 1`,
`created_count = 0`), with both kinds of attempts sharing one history as
shown by `test_import_history.py::test_history_is_organisation_scoped`. Row
message formats are covered by `test_csv_import.py`
(`test_unit_must_match_the_factor`, `test_invalid_values_are_reported`,
`test_error_list_is_capped`).

Header-only rejection (implemented derivation; `backend/emissions/csv_import.py`
labels file-level messages as row 1): outcome `rejected`, `row_count = 1`,
`accepted_count = 0`, `rejected_count = 1`, `created_count = 0`,
`400 "The file has no activity rows."`; the file itself is retained. Under the
implemented counting rule every file-level message (empty file, duplicate or
missing columns, invalid CSV) contributes exactly one rejected row this way.
The header-only counters and message are pinned by
`test_import_history.py::test_header_only_file_is_rejected_with_its_own_counters`
(`row_count = 1`, `rejected_count = 1`, `accepted = created = 0`, message
`"Row 1: The file has no activity rows."`); the other file-level cases follow
from the same rule but are not individually pinned.

**Closing the recorded gap:** the "len(errors)-based counting" gap noted
earlier is resolved — `persist_import` groups errors by row before counting,
with `row_count = created + rejected_rows`; no DB `CHECK` enforces the
resulting invariant.

## History existence, retention and access (implemented; retention still open)

**When history exists:** exactly for requests that are authenticated, have a
file, pass size and UTF-8 preflight, and reach `persist_import` — i.e. every
request the service could store. Outcomes `success`, `rejected`, `failed` are
all first-class history rows. Preflight failures are excluded as decided
above. Unauthenticated requests are rejected by DRF before any counter runs.

**Retention (proposed, needs product decision — open issue):**

 - `success` and `rejected` attempts **keep the stored CSV file**.
 - `failed` DB attempts have already had their upload **deleted** (cleanup
   path policy: the storage reference lives in `ImportLog.stored_file`;
   deletion is by that same reference, so a name can never outlive or
   contradict its row). Nothing in the system should ever reference a path
   string not present in a log's `stored_file`.
 - how long rows + files are kept before pruning, and where told apart from
   the daily **DB-only** backup, is *not decided here*; the proposal stores
   CSVs in `/uploads` and the backup script currently covers the database
   only (B08 must document the upload gap; pruning/retention duration is
   Guillermo's call and must be tracked as an open decision, not silently
   dropped).

**Stored-file convention (implemented):** uploads live under
`private/emissions-imports/<org>/` with a generated hex file name and a
sanitised suffix, computed in `persist_import`; the model field's
`upload_to` matches this through migration
`backend/emissions/migrations/0004_alter_importlog_stored_file.py`. The
client's file name never reaches the storage path
(`test_import_error_paths.py::test_success_stores_file_with_generated_name`).
A failed database attempt clears `stored_file`; both failure outcomes record
fixed safe messages instead of exception text (storage-failure and
database-failure sections above), with both texts pinned verbatim by
`test_import_error_paths.py`.

**Access:** history is readable only within the user's organisation; no
`stored_file` path is exposed in history responses (implemented); any future
file download must re-check authentication and organisation against the log
row (A10), and there must be no public media URL (A05 verifies the actual
serving configuration, since folder names are not access control).

## What A04 must confirm (`makemigrations --check`)

The contract needs **no new model fields**: `row_count`, `accepted_count`,
`rejected_count`, `created_count`, `outcome`, `error_messages` (JSON list of
strings), `stored_file` and `created_at` already carry everything above, and
`accepted_count` vs `created_count` separation exists deliberately. A04 should:

1. run `backend/manage.py makemigrations --check --dry-run` after the A02 fix
   landed (expected: no drift; the existing
   `backend/emissions/migrations/0003_importlog.py` stands),
2. apply nothing new unless a reviewer explicitly requests a field such as a
   per-row structured error list or an upload checksum (both flagged below, not
   silently added),
3. confirm the migration applies cleanly to a disposable test database and
   preserve the existing migration history unchanged.

## Parser metadata (no longer needed)

The planned `CsvImporter` metadata (`data_row_count`, `accepted_rows`,
`rejected_rows`) was not required: `persist_import` derives `rejected_rows` by
grouping the flat error list by `row`, and `created` comes from the saved
records. The consequences are documented in the counting rules above: valid
rows of a rejected batch are not counted, and blank-line skipping plus the
5 000-row break surface only as row errors, not as separate counters. The HTTP
response keeps the flat, capped message list exactly as implemented;
per-row multi-message grouping stays internal parser behaviour.

## Open issues (explicitly not decided here)

1. **Retention duration/pruning** of logs and stored CSVs — proposal target,
   needs the product owner's agreement; until then nothing is deleted except
   the DB-failure cleanup above.
2. **Upload backup coverage** — the backup script is DB-only; uploading-side
   recovery must be documented by B08, restoring the DB alone must not imply
   file restoration.
3. **What remains open after the failure-log work** — (a) the post-rollback
   upload-file delete in the database-failure path is unguarded, so a failing
   delete can mask the original `DatabaseError`; (b) whether the retained
   logs' fixed safe message text is user-facing enough to matter for the
   `/uploads` retention/pruning decision stays with B08 (issue 2 above).
   Message hygiene itself is now implemented and pinned by tests.
4. **Possible future fields** (per-row structured errors, upload checksum) —
   deferred; only if reviewer-requested, only with a migration row and A04
   check.
5. **Failed log counts stay 0** after a DB rollback instead of recording the
   known parser totals — safe but lossy; revisit in A09 only if a safe write
   path exists.
6. **Message-length cap** for echoed CSV cell values — row messages echo cell
   text; A07 should cap or truncate so a giant cell cannot grow the history
   response.
