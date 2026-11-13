# Emissions delivery evidence — checkout, checks and limits

Recorded 11 November 2026 by the D03 evidence worker (task D03 of
`docs/emissions-delivery-plan.md`). Docs-only task: no application code,
dependencies or migrations were touched; the only file written in the repo is
this one. No test suite, lint run, coverage run or Docker command was executed
as a *new* check — everything below is consolidated from recorded runs with
their dates, plus clearly labelled read-only observations made today.

## 1. Checkout identity

| Item | Value |
| --- | --- |
| Branch | `feature/emissions-import-history` |
| Revision at recording | `97c11b5d4bd761c334d1fb6468565d5cc8b3d601` ("chore(infra): add coverage and database backup tools") |
| Origin sync | In sync with `origin/feature/emissions-import-history` (0 ahead / 0 behind at recording) |
| Last mainline merge | `c32e1d5` "Merge pull request #10 … feature/analytics-reporting" (10 November 2026) |
| Interpreter | `.venv/bin/python` → Python 3.13.12; Django 5.2.19 |

The branch contains four emissions commits, all authored 11 November 2026
(committed 11:42–11:43 by the user after the agent work was reviewed):

| Commit | Date | Summary of change |
| --- | --- | --- |
| `3b79fe5` | 11 Nov 2026 | feat(emissions): import history and factor recalculation |
| `4aa24d7` | 11 Nov 2026 | feat(emissions): seed reviewed government emission factors (`data/official_factors.json`, `seed_official_factors` command, its tests, `docs/emission-factor-sources.md`) |
| `9627686` | 11 Nov 2026 | docs(emissions): contract documents, `docs/emissions-verification.md`, `scripts/measure_import_5000.py` |
| `97c11b5` | 11 Nov 2026 | chore(infra): `compose.backup.yaml`, `scripts/backup.sh`, `pytest-cov` pin in `requirements-dev.txt` |

Untracked files in the worktree at recording (none staged, none modified by
this task): `AGENTS.md`, the professor's PDFs and the topic presentation,
`dev.md`, `plan.md`, `script.md`, `script.pdf`, `pipeline-homework2.png`,
`docs/emissions-delivery-plan.md`, and the two empty management package
markers analysed in section 4. During this task the sibling D01 deliverable
`docs/emissions-class-inventory.md` also appeared in the shared worktree; it
belongs to another worker and was not read or modified here.

## 2. Check evidence ledger (attributed, not rerun)

### 2.1 Latest recorded run — parent session, 11 November 2026, this checkout

Recorded in the delivery plan (`docs/emissions-delivery-plan.md`, working
rules) as: **271 tests passed**, Django `check` clean (0 issues), `ruff check`
and `ruff format --check` clean (128 files). These figures describe the run on
`97c11b5`; they were **not rerun by D03** and no log file is archived in the
repository — the plan text itself is the only record. Two consequences:

- If the final revision moves past `97c11b5`, this whole evidence sheet needs
  re-anchoring before submission (section 6).
- The jump from the previously documented 240 tests (section 2.2) to 271 came
  from later development rows whose runs are not archived anywhere in the repo
  documents; only the final count is recorded.

### 2.2 Documented historical trail — `docs/emissions-verification.md` (10 November 2026)

That document preserves the run-by-run history of the import-history feature
and is worth keeping for the record, including its failures:

| Row / date | Evidence recorded |
| --- | --- |
| A01 (10 Nov) | `check` passed; **217 tests: 17 failed** (all CSV-import/department endpoint tests), 9 ruff errors, 4 unformatted files — the partial work was broken at that point, and the document says so. |
| A02 (10 Nov) | Repairs landed (undefined `StorageError`, blanket `except Exception`); 222 passed; touched files lint/format clean. Introduced the durable in-test media-isolation fixture. |
| A08 (10 Nov) | 240 passed; **coverage 94 %** for `backend/emissions` (707 statements, 40 missed, SQLite); 5,000-row import benchmark (section 2.3); full lint/format/`check` clean. |

Two statements in the A08 appendix are now outdated and must not be copied
forward: it says `scripts/` is untracked in git (resolved —
`scripts/measure_import_5000.py` is tracked as of `9627686`), and its commands
reference the temporary `carbondesk_temp_settings` wrapper in `/tmp/opencode`
(no longer present; the documented current runs are plain `pytest` per the
README, with the in-test fixture still providing upload isolation). This file
is owned elsewhere (D02/D07/D09 correct it); D03 only flags the staleness.

### 2.3 Performance and coverage — one-setup evidence, known limits

- **Coverage 94 %** (`--cov=emissions`, 707 statements, 40 missed) was measured
  on **10 November 2026 with a 240-test suite on SQLite**. About 31 tests were
  added afterwards; the figure has **not** been remeasured and must not be
  quoted as current. The proposal's ≥ 80 % target was met on that setup only.
- **~1.4 s for a 5,000-row import** (1.43–1.45 s valid; 0.08 s rejected batch)
  was measured on **SQLite** in a disposable database, one machine, real HTTP
  flow (`scripts/measure_import_5000.py`, tracked and rerunnable). The
  proposal's < 10 s target was met **on SQLite, on that machine**. PostgreSQL
  was never benchmarked; per the delivery plan this is deferred, so no
  PostgreSQL performance claim exists at all.
- The `ImportLog` counting contract and failure paths these tests pin are
  documented in `docs/emissions-import-contract.md`; the totals surface other
  subsystems consume is documented in `docs/emissions-totals-api.md`; factor
  provenance (verified UK DESNZ 2025 subset) is documented in
  `docs/emission-factor-sources.md`.

### 2.4 No CI

There is no `.github/workflows/` configuration; every check in this sheet is a
local manual run. A push does not re-verify anything, which raises the value
of the pre-submission rerun listed in section 6.

## 3. Docker startup evidence — and what it does not cover

**Prior observed run (parent session, 11 November 2026, this checkout):**
`docker compose up --build -d` from the repository root succeeded; the backend
container applied Django migrations against PostgreSQL, passed its healthcheck
(`GET /api/health/`), and the frontend served HTTP 200. Attributed to that
recorded run; not rebuilt or rerun by D03.

**Read-only observation today (11 November 2026, `docker compose ps` only):**
all three services are `Up (healthy)` — `db` (postgres:17-alpine), `backend`
(published on 127.0.0.1:8000) and `frontend` (127.0.0.1:8080). The `db`
container is five days old (its `postgres_data` named volume predates the
current branch), while the backend and frontend containers were recreated
shortly before the observation, consistent with the parent's recent
`up --build -d`. Nothing was started, stopped or changed.

**What this evidence deliberately does not cover:**

- No **full browser demo** was verified on this revision: the end-to-end
  click-through (register/seed organisation → factor → activity form →
  CSV import → import history → totals) has not been demonstrated on
  `97c11b5`. The Docker healthchecks are shallow HTTP probes, not functional
  verification of the emissions feature set.
- No **clean-clone proof**: every observed run used this (or a prior) working
  tree. A fresh `git clone` has never been built and started.
- No PostgreSQL **performance or coverage** measurement (deferred, section
  2.3), and no backup-restore validation of `compose.backup.yaml`
  (`scripts/backup.sh` is DB-only; upload recovery stays open, see the import
  contract's open issues).

## 4. Untracked Python package markers — analysis and recommendation

**Facts.** `backend/emissions/management/__init__.py` and
`backend/emissions/management/commands/__init__.py` are **empty (0 bytes) and
untracked**. The seed commit `4aa24d7` added
`management/commands/seed_official_factors.py` but not the two markers
(`git ls-files backend/emissions/management/` lists only the command file).
Both marker files were created in the worktree on 10 November 2026 and never
staged. Note that `backend/emissions/__init__.py` and
`backend/emissions/migrations/__init__.py` **are** tracked, so only the
management chain is affected.

**Relevance to a fresh clone.** Git cannot store empty directories, but the
directories themselves *do* exist in a fresh clone, because the tracked
`seed_official_factors.py` sits inside them. The question is whether Django
5.2 discovers and loads the command without the marker files. Static reading
of the installed Django (5.2.19) source:

- `django.core.management.find_commands` enumerates the `commands` directory
  directly with `pkgutil.iter_modules([command_dir])` — it never imports
  `emissions.management`, so discovery does not need the markers.
- `django.core.management.load_command_class` imports
  `emissions.management.commands.<name>`; on CPython 3.3+, subdirectories of a
  regular package without `__init__.py` are namespace packages and import
  successfully.

**Empirical probe (11 November 2026).** A minimal tree reproducing the exact
fresh-clone shape — regular `emissions` package (tracked `__init__.py`),
`management/` and `management/commands/` without markers, a stub
`seed_official_factors.py` — was created under `/tmp/opencode/d03-nsprobe/`
(outside the repo) and exercised with the real Django 5.2.19 on CPython
3.13.12: `find_commands` returned `['seed_official_factors']` and
`load_command_class("emissions", "seed_official_factors")` instantiated the
command successfully. The same reasoning applies to the Docker path, since
`backend/Dockerfile` copies the checked-out `backend/` tree onto
`python:3.13-slim` (CPython 3.13).

**Conclusion.** The missing markers are **not evidence of a broken clone**, and
the documented seed command is expected to work in a fresh clone on the
project's standard setup. Caveats, stated honestly:

- This is mechanism analysis plus a stub probe, **not an observed run on an
  actual clean clone** (section 3 records that none exists).
- Namespace-package loading is standard CPython behaviour but is more
  tooling-sensitive than regular packages (bundlers/zipapps can differ); that
  does not apply to the documented venv/Docker workflows.

**Recommendation.** Include both empty `__init__.py` files in the delivery
handoff when staging. They are zero-cost, conventional for Django management
packages, consistent with the tracked `migrations/__init__.py`, and they
remove the only clone-related doubt in this area. Staging them is a user
decision under commit-guide; D03 did not stage anything.

## 5. Fresh-clone caveats (consolidated)

- The two management markers (section 4) — expected harmless, recommended for
  inclusion.
- `.env` is untracked by design; the documented setup starts from
  `cp .env.example .env` (README, "Run with Python" / "Run with Docker
  Compose").
- `backend/media/` does not exist in a clone; Django and the compose
  `media_data` named volume create it at runtime. The import contract's
  retention questions (upload backup is DB-only) remain open regardless.
- The reviewed government factor seed (`seed_official_factors`) ships with the
  clone, but it seeds **one explicit organisation by primary key** and the
  README demo factor ("Demo electricity", 0.4 kg CO2e/kWh) is created by hand;
  there is no automatic demo-data seed.
- No CI (section 2.4): a clone must run the README check commands itself.
- `pytest-cov==7.1.0` is pinned in the tracked `requirements-dev.txt`, so the
  documented coverage command works after a standard install.

## 6. Outstanding human delivery work

From the delivery plan's finish line and the parent's brief; none of this may
be claimed as done by any agent:

1. **Guillermo:** verify the class inventory/diagram deliverables (D01, D04,
   D05) against his own code, rehearse the subsystem explanation and demo
   (D06), and confirm which deferred proposal items to state as deferred
   (no PostgreSQL benchmarking, no import-history UI beyond the API, no
   factor-catalogue expansion, no backup-restore project).
2. **Staging and commits:** user decision under commit-guide — including the
   two empty package markers (section 4) and the documentation set; D03
   staged nothing. Then push the feature branch and merge it into the final
   team branch (team coordination, not an agent action).
3. **Team presentation/video:** combine the members' contributions for the
   15–20 minute live presentation (requirements PDF, p. 7). Separately resolve
   the recording duration: the requirements PDF, p. 4, asks for a seven-minute
   screencast, while the final reminder, p. 1, asks for a five-minute video.
   Record/upload the agreed video and add its real README link; placeholders
   do not count as delivery.
4. **Submission logistics:** book one ILIAS presentation slot (14 or
   21 November 2026), attend in person with student ID, meet the 13 November
   capstone upload date, and decide on repository visibility/publication.
5. **Pre-submission rerun:** if the final revision differs from `97c11b5` — or
   regardless, before upload — rerun the README check set (tests, `check`,
   ruff) and, ideally, one fresh-clone `docker compose up --build` demo, and
   update this sheet's attribution dates.

## 7. What this task actually performed

- Read-only inspection: `git status/rev-parse/log/ls-files/merge-base`,
  `git show --stat`, `docker compose ps`, file reads of the emissions docs,
  README, compose files, Dockerfiles, `.dockerignore`, the untracked marker
  files, the seed command, and Django 5.2.19's `django/core/management`
  source in `.venv`.
- One outside-repo probe in `/tmp/opencode/d03-nsprobe/` (section 4) using
  `.venv/bin/python`; repo files untouched by it.
- Consistency checks for this document: every path referenced here exists on
  the current checkout (`docs/emissions-verification.md`,
  `docs/emissions-import-contract.md`, `docs/emissions-totals-api.md`,
  `docs/emission-factor-sources.md`, `docs/emissions-delivery-plan.md`,
  `scripts/measure_import_5000.py`, `scripts/backup.sh`,
  `compose.backup.yaml`, `requirements-dev.txt`,
  `backend/emissions/management/commands/seed_official_factors.py`), and the
  figures quoted from them were checked against their sources.

Not performed (out of scope for a documentation task): pytest, ruff, Django
`check`, coverage, benchmarks, `docker compose` lifecycle commands, a
clean-clone build, any browser demo, and any file edit outside this document.

## 8. Known limitations of this evidence sheet

- The parent's 271-test/128-file figures (11 November 2026) are cited from the
  delivery plan text; no command log is archived in the repository.
- The 94 % coverage and ~1.4 s benchmark are single-setup historical results
  (SQLite, 10 November 2026 suite) — see section 2.3 for why they are not
  current claims.
- No clean-clone or full-browser-demo verification exists; the sections above
  separate startup evidence from functional-demo evidence accordingly.
- The professor-document requirements referenced here (video duration,
  submission dates) are carried over from `AGENTS.md` and the delivery plan;
  the requirements PDF pages themselves were not reread in this task, and the
  duration conflict stays unresolved (section 6, item 3).
