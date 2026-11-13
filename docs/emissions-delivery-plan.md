# Emissions delivery: small agent tasks

Updated 11 November 2026. Owner: Guillermo Pérez Pérez.
This is the active remaining-work plan; it supersedes unfinished feature queues
in `dev.md` and `plan.md`. The user chose to defer non-critical proposal items.
Workers: **OpenCode GLM-5.3-Flash Free, Max effort** (`variant: max`, subject to
availability verified at launch). Execution authorized: one dedicated worker per task,
with dependencies respected. Independent reviewer: **GPT-6-Astra, medium effort**.

## Scope

Finish the implemented emissions UML, accurate emissions documentation and
Guillermo's presentation/demo material. No chatbot, accounts or analytics work.
No new import-history UI, factor-catalogue expansion, performance optimization,
PostgreSQL benchmarking or backup-recovery project. Record these as deferred;
do not describe the original proposal as fully fulfilled.

Sources to read: `AGENTS.md`, current `README.md`, relevant emissions code,
`capstone project requirements 2026 python.pdf` pp. 4, 6–7 (submission,
readiness, presentation), proposal slide 2 and notes, and final reminder p. 1.
The requirements PDF asks for subsystem UML and unit-test results, and a
15–20 minute team presentation. Its seven-minute screencast conflicts with the
final reminder's five-minute video: record the unresolved duration, do not
invent a precedence or require Guillermo to make both recordings.

## Working rules

- One task per worker turn, with one tangible output. Inspect existing work first.
- Start with at most three workers concurrently. Do not spawn nested agents.
- Each file has one owner. Only D07 edits README; only the parent updates this
  plan/status. Do not modify application code, dependencies or migrations.
- Use `.venv/bin/python`, never bare `python`, for local Python commands.
- No staging, commits, pushes, PR creation/merge or uploads in these tasks.
  The user handles commits under commit-guide. Publication remains a later step.
- Use current code for implementation claims. Old verification notes include
  historical failures; retain their history but identify the latest evidence.
- Last observed checks: 271 tests passed, Django check and Ruff checks passed.
  Attribute those to the recorded run; do not claim a fresh run or unchanged
  coverage. The 94% coverage and ~1.4-second benchmark are earlier SQLite results.
- Documentation tasks need link/consistency checks, not a full test rerun. If
  the final code revision changes, flag evidence needing refresh.
- Report substantive code defects found during reading to the parent; do not
  silently fix them or label them harmless just because enhancements are deferred.

## Execution status

- D01 and D02: delivered; parent reconciled D02 packaging and script-tracking
  claims against D03 and git. Independent final review pending.
- D03: delivered; parent checked evidence attribution and clarified live presentation
  versus screencast durations. Independent final review still pending.
- D04–D06: delivered. D05 completed by GPT6-Luna after the GLM quota failure;
  parent inspected the PNG and confirmed rendering notes exist. Full-page text
  remains small; use the SVG with zoom. Final independent review pending.
- D07: prerequisites ready; original GLM worker provider hit its free quota.
- D08–D10: waiting for README integration.

## Task queue

Use the execution status above for progress. Existing source material is input,
not a task completion claim. Proposed new file paths are deliverables to create.

| ID | Owner role | Depends on | Allowed output | Done when |
| --- | --- | --- | --- | --- |
| D01 | UML worker | None | `docs/emissions-class-inventory.md` | List actual classes, key fields/public methods and relationships with code references; distinguish classes from module functions |
| D02 | Documentation worker | None | `docs/emissions-readme-notes.md` | Draft precise README corrections: imports endpoint, seed command, demo flow, known limits and documentation links; no README edit yet |
| D03 | Evidence worker | None | `docs/emissions-delivery-evidence.md` | Record branch/revision, existing check evidence and limits; identify untracked Python package markers and any fresh-clone caveats; separate local Docker startup evidence from full demo verification |
| D04 | UML worker | D01 | `docs/diagrams/emissions-classes.mmd` | Class diagram source matches inventory, shows cardinalities and external accounts references, with no invented methods or relationships |
| D05 | UML worker | D04 | `docs/diagrams/emissions-classes.svg`, `.png` and rendering notes in inventory | Render source with an available diagram tool; inspect image for clipping/readability and verify labels against source; record exact rendering command |
| D06 | Presentation worker | D01, D03 | `docs/emissions-presentation-notes.md` | Prepare Guillermo's explanation outline and reproducible demo steps, expected results, errors and useful test examples; no fabricated recording/video link |
| D07 | README integration worker | D02, D03, D05 | `README.md` only | Apply emissions-only corrections, embed rendered UML, link seed/contract/evidence docs and state deferred items; preserve teammates' sections |
| D08 | Reviewer | D05, D06, D07 | Findings returned to parent, no edits | Independently compare code/UML/README/demo claims, verify links and correct ownership; report severity and exact file references |
| D09 | Original file owners | D08 findings | Only files named in findings | Fix documentation/diagram defects; parent checks small corrections; material revisions receive a fresh review task |
| D10 | Parent | D09 or clean D08 | Status update and commit-guide handoff | Review complete diff, identify exact deliverable files, provide user staging/commit/push instructions and PR-to-main next step without performing publication |

D03 should flag the two currently untracked package markers:
`backend/emissions/management/__init__.py` and
`backend/emissions/management/commands/__init__.py`. They were omitted from the
previous seed commit. Inspect their relevance and include them in the delivery
handoff if appropriate; don't claim a broken clone solely from their absence.

## Narrow briefs and acceptance details

### D01 and D04: class diagram content

Start with `ActivityRecord`, `EmissionFactor`, `ImportLog`, `CO2eCalculator`,
`CsvImporter`, `ImportedActivity` and `EmissionsError`. Show external `Organisation`,
`Site`, `Department` and user relationships only where needed to explain ownership.
Inspect actual FK optionality and deletion rules. Do not invent an activity-to-
ImportLog FK: inspect the implementation before drawing any relationship.
`create_activity`, `persist_import`, `recalculate_factor_records` and totals
helpers are module functions, not a `Service` class. Explain their orchestration
in a note or accompanying prose. Keep the class diagram readable; omit Django
internals and nonessential fields. Homework streaming classes are separate from
the web subsystem and need not crowd this diagram.

### D02 and D07: documentation content

Document `GET /api/emissions/imports/` as a backend endpoint, not an existing UI.
Show the explicit organisation seed command using the persisted unit-labelled
factor names. Explain factor snapshots and explicit recalculation, CSV atomicity,
current history counter meaning and limitations. Verify these against code;
don't copy stale aspirations from `dev.md`. Use synthetic demo data in examples.
Keep current setup: Docker Compose starts the three local services and runs
migrations. Do not claim KIConnect integration or production deployment.

### D06: demonstration and learning

Prepare a short modular contribution, not a finished team presentation. Include:
form preview/save (100 kWh × synthetic 0.4 = 40.00 kg CO2e), valid/invalid CSV,
explicit factor recalculation with retained audit history, and totals consumed by
other subsystems. Choose a manageable subset for recording. Explain roles of
models, calculator, importer and service functions, Decimal rounding and backend
permissions. Include a few questions Guillermo should be able to answer himself.
No requirement to build slides or record video during this task.

### D08: review boundaries

The user selected GPT-6-Astra at medium effort for independent review. This
supersedes the previous Antigravity reviewer preference. Do not substitute
another model silently. Every new delegated review is a
fresh review task. Review deliverables, not speculative new functionality.

## Suggested launch waves

1. D01 + D02 + D03, each with exclusive files.
2. D04 and D06 after their prerequisites pass.
3. D05, then D07.
4. D08, bounded fixes D09, then D10.

Do not assign all rows to one small-model worker. A single-file task completion
must include the output path, checks actually performed and any unresolved claim.

## Human/team finish line

Guillermo checks the diagram and rehearses his explanation, commits/pushes the
reviewed documents and gets the feature branch merged into the final team branch.
The team combines presentation material, confirms video duration, records/uploads
and adds the real link. These require human content/coordination; agents must not
pretend they are completed. This plan does not authorize publishing or submission.

## Copyable worker prompt

> Complete DXX only in docs/emissions-delivery-plan.md using GLM-5.3-Flash Free
> Max. Read AGENTS.md and the specified current inputs. Allowed outputs: [paths].
> Produce [deliverable] and perform [checks]. Preserve existing work. Do not edit
> other files, add features, spawn agents, stage, commit, push or upload. Return
> actual changed paths, evidence and unresolved questions. Stop at this row.
