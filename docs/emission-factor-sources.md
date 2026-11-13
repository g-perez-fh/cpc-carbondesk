# Emission factor sources

## Verified UK Government 2025 factors

Source: [Greenhouse gas reporting: conversion factors 2025](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025), published 10 June 2025 by the Department for Energy Security and Net Zero (DESNZ).

Attachment used: **Conversion factors 2025: flat file (for automatic processing only)** —
`https://assets.publishing.service.gov.uk/media/6846b6ea57f3515d9611f0dd/ghg-conversion-factors-2025-flat-format.xlsx`
(505,634 bytes; SHA-256 `8bfdb45b81ec4a88e3bdf4584637330f62e6bd09ce1940e654c5d7b7f736de94`).

On 2026-11-10 the attachment was downloaded directly from the `assets.publishing.service.gov.uk` URL
above and compared byte-for-byte with the local working copy `/tmp/official.xlsx`: both files hash to
the same SHA-256, so the local workbook is identical to the official GOV.UK attachment. The workbook's
internal document properties confirm the identity ("UK Government GHG Conversion Factors for Company
Reporting: Flat File Format", creator DESNZ, last modified 2025-06-03).

### Workbook structure

The flat file contains two worksheets: `Front page` and `Factors by Category` (the second sheet).
`Factors by Category` has 8,748 rows. Row 6 is the header row with columns: `ID`, `Scope`,
`Level 1`–`Level 4`, `Column Text`, `UOM`, `GHG/Unit`, and `GHG Conversion Factor 2025`. The year
column is therefore the `GHG Conversion Factor 2025` column (column J); 2025 is the factor year both
entries use.

The values below were checked in that sheet. Values are the aggregate greenhouse-gas rows
(`GHG/Unit` = `kg CO2e`), not the separate per-gas component rows that follow each of them
(`kg CO2e of CO2/CH4/N2O per unit`), and the factor is expressed as kg CO2e per workbook UOM.

| Workbook row | ID | Factor | Scope | UOM | GHG/Unit | 2025 factor |
| --- | --- | --- | --- | --- | --- | ---: |
| 7 | 1_100_1000_15_1 | Butane (Fuels / Gaseous fuels) | Scope 1 | tonnes | kg CO2e | 3033.38067 |
| 11 | 1_100_1000_8_1 | Butane (Fuels / Gaseous fuels) | Scope 1 | litres | kg CO2e | 1.74533 |

The values are used exactly as published in column J; no conversion or rounding was applied.
As a plausibility check, the per-gas component rows for the tonne factor (rows 8–10: CO2 3029.26 +
CH4 2.52 + N2O 1.60067) sum exactly to 3033.38067. For litres (rows 12–14) the published components
sum to 1.74532, one unit in the fifth decimal place below the published aggregate 1.74533; the
components are rounded independently, so our subset uses the published aggregate row.

### Combustion vs upstream boundary

The two verified factors cover **direct combustion only** (Scope 1 tank-to-(unit use) burning of the
fuel). They do **not** include upstream emissions from producing and transporting the fuel. The same
workbook publishes these upstream factors separately, under `Level 1` = `WTT- fuels`, `Scope 3`
(`WTT` = well-to-tank). For butane those upstream rows are:

| Workbook rows | Scope / level | UOM | 2025 kg CO2e (upstream, not used) |
| --- | --- | --- | ---: |
| 3458–3461 | Scope 3, WTT- fuels / Gaseous fuels / Butane | tonnes, litres, kWh (Net/Gross CV) | 344.30947 (tonnes), 0.19765 (litres) |

These upstream factors are deliberately not part of our subset. They are different quantities: a
combustion factor describes burning the fuel, a WTT factor describes producing and delivering it. Do
not merge a WTT factor into a Scope 1 combustion factor or use them to double-count the same fuel
activity. This does not stop a properly scoped company inventory from reporting both kinds of
emission: the combustion share is a Scope 1 activity and the well-to-tank share is a separate
Scope 3 activity, each calculated with its own factor. The publication's methodology paper
(`2025-GHG-CF-methodology-paper.pdf`, linked from the same publication page) documents how the
factors are derived.

Note on scopes: butane appears in this workbook only under `Scope 1` (combustion, rows 7–22) and
`Scope 3` WTT rows 3458–3461. Our subset stores it as Scope 1 combustion.

## Limits

This is a deliberately small verified subset: it contains only the two butane entries above. It does
not constitute the full UK Government catalogue, and no UBA factors are included — that part of the
proposal's factor sources remains an explicit, unresolved gap. Do not treat either unit's value as
interchangeable with the other or apply it to a different fuel/category without checking the official
source and unit compatibility. The published factor describes its stated reporting conversion; this
subset does not add lifecycle boundaries, company-specific assumptions, or other emission sources.

### Stored factor names (CSV lookup)

The table above keeps the original workbook names (`Butane`). When persisted through the seed
command, each factor receives exactly one unit suffix, so the stored names are `Butane (tonnes)` and
`Butane (litres)`. The two entries share the workbook name and the year 2025 but differ in unit, so
storing the unit in the name is what keeps the importer's name-and-year lookup unique: CSV files must
reference these stored names, and a lookup by workbook name alone would still be ambiguous. The same
mapping is recorded in the dataset's `persisted_names` field. Should the naming convention ever
change, change it in one place (the seed command) and update `persisted_names` and this section
together, so that there is always exactly one suffix and no double-labelled names such as
`Butane (tonnes) (tonnes)`.

## Seeding into an organisation

```bash
.venv/bin/python backend/manage.py seed_official_factors --organisation-id <ID>
```

The command requires an explicit `--organisation-id`. A test also verifies that this documented
invocation matches the actual command parser (required `--organisation-id` option), so the usage line
above cannot silently drift from the interface.

Rerun-safety rules are implemented and covered by the tests in
`backend/emissions/tests/test_seed_official_factors.py`: an identical rerun is skipped without
changing factor ids or values; a conflicting custom factor, a conflicting factor already used by
activities (whose stored snapshots stay untouched), and an ambiguous name/year duplicate all abort
the run without overwriting anything; a conflict on the second dataset entry proves the first
insertion is rolled back atomically. Seeding never writes audit history. Omitting `--organisation-id`
or passing an ID that does not exist fails with a clear command error and performs no writes.
Two organisations can be seeded independently: each receives its own factor rows with separate
primary keys, and the first organisation's rows are untouched by the second seeding.

Verified test results: 10 passing tests in `backend/emissions/tests/test_seed_official_factors.py`
(Python 3.13.12, pytest 9.2.0, pytest-django 4.14.0, Django 5.2.19, isolated in-memory SQLite test
database, no network access and no runtime data — the command reads only the reviewed local JSON
dataset).

Limitations: this dataset covers only the two butane combustion factors; the UBA part of the
proposal's factor sources remains an explicit unverified gap. Seeding happens on demand per
organisation; there is no automatic catalog update, and factors already in the database are never
modified by the seed command — conflicts must be resolved manually. The tests use clearly labelled
synthetic factors and activities in an isolated test database.
