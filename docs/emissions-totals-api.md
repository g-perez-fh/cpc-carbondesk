# Totals exposure — integration contract for the totals API

Status: **implemented baseline with named proposed items**, written in dev row
A10 (10 November 2026). This document describes what the other subsystems
(dashboard — Harib Khalid, assistant — Omotunde Sholola Ganiyu, NiceGUI
frontend) can rely on from the emissions subsystem's totals surface **today**,
and which proposed requirements still need a team agreement before anyone
implements them. Like the import contract, the tables mark where current code
already behaves this way and where something is only proposed. Consumers are
strongly advised to code against this contract and raise disagreements here
instead of reaching around it.

Everything below is an engineering agreement inside our team, not a professor
requirement.

## Implemented: HTTP endpoints the other subsystems may rely on

### `GET /api/emissions/summary/` (implemented, tested)

Company-scoped totals for a filtered activity window.

| Property | Contract |
| --- | --- |
| Auth | Unauthenticated → **401**; authenticated user without an organisation → **403**; any member (viewer included) → 200. Roles never change a GET response. |
| Org isolation | Only records of the user's own organisation are ever counted; a foreign organisation's user sees an all-zero summary, never another company's data. |
| Request filters | `start` (inclusive), `end` (exclusive; `end <= start` → 400 "End must be after start (end is exclusive)."), `scope` (`1|2|3`), `site` (primary key; must belong to the user's organisation → foreign id → 400). All optional; combined with AND. |
| Response fields | `count` (records in window), `demo_count` (subset flagged `is_demo`), `total_kg_co2e` (sum, string), `by_scope` (keys `"1"`,`"2"`,`"3"`, values as strings), `unit` (`"kg CO2e"`). |
| Number format | **Decimal-as-string with two decimals** on HTTP (`"40.00"`, `"0.00"`); no floats cross the API. `count`/`demo_count` are real JSON numbers. |
| Empty window | An all-zero 200 summary (`count = 0`, scopes `"0.00"`), never an error. |

Response shape pinned by `test_emissions.py::test_summary_shape_units_and_empty_scope`;
auth by `test_summary_requires_authentication_and_membership`; filtering and
consumer totals by `test_filter_dates_and_consumers_use_real_totals`,
`test_invalid_filters_return_400` and
`test_pagination_keeps_summary_total_for_all_records`.

### `GET /api/emissions/activities/` (implemented, paginated)

The record list behind the summary: page-paginated activity rows (20/page;
`count` reflects the whole filtered window, not the page). Consumers compute
breakdowns from it only when a dedicated endpoint does not exist yet (see open
items). Same filters, auth and isolation as the summary. This is what the
NiceGUI emissions page uses today (`frontend/pages/emissions.py`).

### `POST /api/emissions/preview/` (implemented)

Stateless recalculation preview (`{"kg_co2e": "...", "unit": "kg CO2e"}`) used
by the frontend factor work. Not a totals contract; listed for completeness.

## Implemented: service-level seam (no HTTP)

`backend/core/emissions_data.py` is the deliberate seam so the assistant and
future consumers do not import emissions models:

- `emissions.services.totals_by_scope(organisation, start, end) → dict[int, Decimal]`
  — kg CO2e per scope (1, 2, 3), **`start ≤ date < end`** (end exclusive, same
  semantics as HTTP), `Decimal` values (not strings — the HTTP layer owns
  formatting). Consumed by `assistant.context.build_snapshot` (year and
  previous-year windows).
- `emissions.services.scope_totals(records)` — query-set→scope-totals helper;
  used by `SummaryView` and by `analytics/services.py` (dashboard, read-only).
- Assistant/auth targets: `ReductionTarget`, `TargetProgress` and
  `target_progress` live in the **accounts** subsystem (Omotunde). The
  emissions API exposes **no** target data today; the assistant reads
  `organisation.targets.all()` directly.

Change rule: the seam's signatures (`totals_by_scope`, `scope_totals`) may not
change meaningfully without updating this contract and flagging the assistant
and analytics owners first.

## Who consumes what today (survey, 10 November 2026)

| Consumer | Reads | Via |
| --- | --- | --- |
| NiceGUI frontend, emissions page | summary + paginated activities | HTTP (token per user, per `backend/config/settings.py` comment) |
| NiceGUI frontend, analytics page | dashboard aggregates | HTTP `/api/analytics/*` (not the emissions summary) |
| Dashboard subsystem (Harib) | raw `ActivityRecord` queryset + `scope_totals` + `ActivityFilterSerializer` | direct read-only import from emissions |
| Assistant (Omotunde) | scope totals per calendar year + previous year | `core.emissions_data.totals_by_scope` seam |
| Targets/alerts (Omotunde) | targets and their progress | accounts' own models/services (no emissions dependency) |

## Proposed — NOT implemented, needs team agreement

These are open questions for the next integration session; do not build them
silently.

1. **Period aggregations for the dashboard.** The proposal's monthly trend and
   site/department comparisons are currently computed by `analytics` reading
   raw records directly. If emissions should serve these (a
   monthly-by-scope series endpoint, or site/department breakdowns), that is
   new contract work — propose the fields before implementing; kpi_snapshots
   itself belongs to the **dashboard subsystem's own design**.
2. **Target-progress read model on the emissions side.** None exists.
   Dashboard target progress relies on accounts + own aggregation; if the
   dashboard wants "expected vs actual kg CO2e per scope for a period" from
   emissions, the field set must be agreed first.
3. **Exact period conventions across subsystems.** HTTP and the seam both use
   end-exclusive ranges; any future monthly/quarterly parameterisation should
   stick to that (dated windows, year/month helpers in `core.emissions_data`).
4. **Snapshot versioning.** `total_kg_co2e` changes the moment an activity is
   edited, deleted, recalculated after a factor correction, or a batch import
   lands. Consumers must not cache forever; a `data_version`/timestamp field
   (proposal §3's "report date and data version") is a candidate addition if
   the team wants explicitness — proposed only.
5. **Units beyond kg CO2e.** If a later requirement asks for tonnes or CO2e
   variants, numbers change meaning, not just labels: new fields, not silently
   re-scaling existing ones.

## Non-goals

- No new emissions endpoints or fields were added in this row; writing the
  contract documented the surface instead of inventing one.
- The emissions subsystem takes no dependency on `ReductionTarget` — target
  semantics stay in the accounts subsystem.
