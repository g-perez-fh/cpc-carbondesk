"""Activity entry and company emissions, using the existing authenticated API."""

from datetime import date
from decimal import Decimal

from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import api, session
from frontend.components import call_api, kg
from frontend.layout import page_layout

SCOPES = {1: "Scope 1 · Direct", 2: "Scope 2 · Energy", 3: "Scope 3 · Indirect"}
CSV_TEMPLATE = (
    "date,description,site,factor,factor_year,quantity,unit\n"
    "2026-01-31,January office electricity,Main office,Demo electricity,2026,100,kWh\n"
)


def number(value):
    return (
        format(Decimal(str(value)), "f").rstrip("0").rstrip(".")
        if "." in str(value)
        else str(value)
    )


@ui.page("/emissions")
async def page():
    if not session.token():
        return RedirectResponse("/login")
    # Refresh roles after an admin changes a user's access in another session.
    try:
        profile = await api.get("accounts/me/")
    except api.ApiError:
        return RedirectResponse("/login")
    session.sign_in({"token": session.token(), "user": profile})
    with page_layout("Emissions"):
        screen = EmissionsPage()
    await ui.context.client.connected()
    await screen.load()


class EmissionsPage:
    def __init__(self):
        self.factors = []
        self.sites = []
        self.departments = []
        self.filters = {}
        self.page_number = 1
        self.can_edit = session.can_edit()
        with ui.row().classes("w-full items-center justify-between gap-4"):
            ui.label("Turn everyday activity into a clear carbon record.").classes("text-gray-600")
            if self.can_edit:
                with ui.row().classes("items-center gap-2"):
                    self.add_button = ui.button(
                        "Add activity", icon="add", on_click=lambda: self.activity_dialog()
                    )
                    self.add_button.props("unelevated color=teal-9 no-caps")
                    self.import_button = ui.button(
                        "Import CSV", icon="upload_file", on_click=self.import_dialog
                    )
                    self.import_button.props("outline color=teal-9 no-caps")
                    self.add_button.disable()
                    self.import_button.disable()
            else:
                ui.badge("Read-only access", color="grey-7").props("outline")
        self.summary_box = ui.column().classes("w-full")
        with ui.tabs().classes("w-full text-teal-900") as tabs:
            activity_tab = ui.tab("Activity records", icon="receipt_long")
            factor_tab = ui.tab("Emission factors", icon="science")
        with ui.tab_panels(tabs, value=activity_tab).classes("w-full"):
            with ui.tab_panel(activity_tab).classes("p-0 pt-4"):
                with ui.row().classes("w-full items-end gap-3"):
                    self.start = ui.input("From", placeholder="Any date").props(
                        "type=date outlined dense"
                    )
                    self.end = ui.input("Before (exclusive)", placeholder="Any date").props(
                        "type=date outlined dense"
                    )
                    self.scope = (
                        ui.select({0: "All scopes", **SCOPES}, value=0, label="Scope")
                        .props("outlined dense")
                        .classes("w-44")
                    )
                    self.site = (
                        ui.select({0: "All sites"}, value=0, label="Site")
                        .props("outlined dense")
                        .classes("w-44")
                    )
                    ui.button("Apply", on_click=self.apply_filters).props(
                        "unelevated color=teal-9 no-caps"
                    )
                    ui.button("Reset", on_click=self.reset_filters).props(
                        "flat color=grey-8 no-caps"
                    )
                self.records_box = ui.column().classes("w-full mt-5")
            with ui.tab_panel(factor_tab).classes("p-0 pt-4"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label("Conversion factors with a source you can trace.").classes(
                        "text-gray-600"
                    )
                    if self.can_edit:
                        ui.button(
                            "Add factor", icon="add", on_click=lambda: self.factor_dialog()
                        ).props("outline color=teal-9 no-caps")
                self.factors_box = ui.column().classes("w-full mt-4")
        self.loading = ui.label("Loading your emissions workspace…").classes("text-gray-500")

    async def load(self):
        ok_factors, factors = await call_api(api.get("emissions/factors/"))
        ok_sites, sites = await call_api(api.get("accounts/sites/"))
        self.loading.set_text("")
        if not (ok_factors and ok_sites):
            self.loading.set_text("Could not load the workspace. Refresh the page to try again.")
            return
        ok_departments, departments = await call_api(api.get("accounts/departments/"))
        self.departments = departments if ok_departments else []
        self.factors, self.sites = factors, sites
        self.site.set_options({0: "All sites", **{s["id"]: s["name"] for s in sites}})
        if self.can_edit:
            self.add_button.enable()
            self.import_button.enable()
        self.render_factors()
        await self.load_records()

    async def apply_filters(self):
        self.filters = {
            key: value
            for key, value in {
                "start": self.start.value,
                "end": self.end.value,
                "scope": self.scope.value,
                "site": self.site.value,
            }.items()
            if value
        }
        self.page_number = 1
        await self.load_records()

    async def reset_filters(self):
        self.start.value = self.end.value = ""
        self.scope.value = self.site.value = 0
        await self.apply_filters()

    async def load_records(self):
        ok_summary, summary = await call_api(api.get("emissions/summary/", params=self.filters))
        ok_rows, data = await call_api(
            api.get("emissions/activities/", params=self.filters | {"page": self.page_number})
        )
        self.summary_box.clear()
        self.records_box.clear()
        if not (ok_summary and ok_rows):
            with self.records_box:
                ui.label("Records could not be loaded. Check the filters and try again.").classes(
                    "text-red-700"
                )
            return
        with self.summary_box:
            with ui.row().classes(
                "w-full rounded-xl bg-emerald-50 border border-emerald-100 p-5 gap-8 items-center"
            ):
                with ui.column().classes("gap-1 grow"):
                    ui.label("RECORDED EMISSIONS").classes(
                        "text-xs font-semibold tracking-widest text-emerald-800"
                    )
                    ui.label(kg(summary["total_kg_co2e"])).classes(
                        "text-3xl font-semibold text-emerald-950"
                    )
                    ui.label(f"Activities: {summary['count']} · current filters").classes(
                        "text-sm text-emerald-800"
                    )
                for scope, label in SCOPES.items():
                    with ui.column().classes("gap-1"):
                        ui.label(label).classes("text-sm text-gray-600")
                        ui.label(kg(summary["by_scope"][str(scope)])).classes("text-lg font-medium")
            if summary["demo_count"]:
                ui.label(
                    f"Includes {summary['demo_count']} activities calculated with demo factors. "
                    "These are not verified emissions."
                ).classes("text-sm text-amber-800")
        with self.records_box:
            if not data["count"]:
                with ui.column().classes(
                    "w-full items-center rounded-xl border border-dashed p-10 gap-3"
                ):
                    ui.icon("eco", size="36px", color="teal-8")
                    ui.label(
                        "No activity records yet"
                        if not self.filters
                        else "No records match these filters"
                    ).classes("text-lg font-medium")
                    ui.label(
                        "Add a factor and a site, then record your first activity."
                        if not self.filters
                        else "Try a different date range, scope, or site."
                    ).classes("text-gray-500 text-center")
                    if not self.sites:
                        ui.link("Manage company sites", "/organisation").classes("text-teal-800")
                return
            rows = [
                {
                    "id": r["id"],
                    "date": r["date"],
                    "description": r["description"],
                    "site": r["site_name"],
                    "scope": f"Scope {r['scope']}",
                    "quantity": f"{number(r['quantity'])} {r['unit']}",
                    "result": kg(r["kg_co2e"]),
                    "kind": "Demo" if r["is_demo"] else "Recorded",
                }
                for r in data["results"]
            ]
            columns = [
                {"name": key, "label": label, "field": key, "align": "left"}
                for key, label in [
                    ("date", "Date"),
                    ("description", "Activity"),
                    ("site", "Site"),
                    ("scope", "Scope"),
                    ("quantity", "Quantity"),
                    ("result", "Emissions"),
                    ("kind", "Data"),
                    ("details", ""),
                ]
            ]
            table = (
                ui.table(columns=columns, rows=rows, row_key="id")
                .classes("w-full")
                .props("flat bordered wrap-cells")
            )
            table.add_slot(
                "body-cell-details",
                """<q-td :props="props">
                <q-btn flat dense no-caps color="teal-9" label="Details"
                    @click="$parent.$emit('details', props.row.id)" />
            </q-td>""",
            )
            records = {r["id"]: r for r in data["results"]}
            table.on("details", lambda event: self.record_dialog(records[event.args]))
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(f"Page {self.page_number} · Records: {data['count']}").classes(
                    "text-sm text-gray-500"
                )
                with ui.row():
                    previous = ui.button("Previous", on_click=lambda: self.change_page(-1)).props(
                        "flat no-caps color=teal-9"
                    )
                    following = ui.button("Next", on_click=lambda: self.change_page(1)).props(
                        "flat no-caps color=teal-9"
                    )
                    if not data["previous"]:
                        previous.disable()
                    if not data["next"]:
                        following.disable()

    async def change_page(self, step):
        self.page_number += step
        await self.load_records()

    def render_factors(self):
        self.factors_box.clear()
        with self.factors_box:
            ui.label(
                "Correct a factor here, then explicitly recalculate linked activities if needed. "
                "Saved activities keep their original calculation until then."
            ).classes("text-sm text-gray-500")
            if not self.factors:
                ui.label(
                    "No factors yet. Add a sourced factor, "
                    "or mark a synthetic example as demo data."
                ).classes("py-6 text-gray-600")
            for factor in self.factors:
                with ui.card().classes("w-full shadow-none border rounded-lg gap-2"):
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.label(factor["name"]).classes("font-medium text-base")
                        ui.badge(f"Scope {factor['scope']}", color="teal-8").props("outline")
                        if factor["is_demo"]:
                            ui.badge("Demo factor", color="amber-9").props("outline")
                        ui.space()
                        ui.label(
                            f"{number(factor['kg_per_unit'])} kg CO₂e / {factor['unit']}"
                        ).classes("font-semibold text-teal-900")
                    ui.label(f"Source: {factor['source']} · {factor['year']}").classes(
                        "text-sm text-gray-600 break-all"
                    )
                    if self.can_edit:
                        with ui.row():
                            ui.button(
                                "Edit factor", on_click=lambda f=factor: self.factor_dialog(f)
                            ).props("flat no-caps color=teal-9")
                            ui.button(
                                "Recalculate activities",
                                on_click=lambda f=factor: self.recalculate_dialog(f),
                            ).props("outline no-caps color=teal-9")

    def factor_dialog(self, factor=None):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl p-6 gap-4"):
            ui.label("Edit emission factor" if factor else "Add an emission factor").classes(
                "text-xl font-semibold"
            )
            ui.label(
                "Use a factor whose unit and category match the activity you want to record."
            ).classes("text-sm text-gray-600")
            name = (
                ui.input("Factor name", placeholder="e.g. Grid electricity")
                .props("outlined dense")
                .classes("w-full")
            )
            with ui.row().classes("w-full gap-3"):
                scope = (
                    ui.select(SCOPES, label="Scope", value=2)
                    .props("outlined dense")
                    .classes("grow")
                )
                unit = (
                    ui.input("Activity unit", placeholder="e.g. kWh")
                    .props("outlined dense")
                    .classes("grow")
                )
            value = (
                ui.input("kg CO₂e per unit", placeholder="e.g. 0.4")
                .props("outlined dense inputmode=decimal")
                .classes("w-full")
            )
            source = (
                ui.input("Source", placeholder="Publication, dataset or source URL")
                .props("outlined dense")
                .classes("w-full")
            )
            year = (
                ui.input("Source year", value=str(date.today().year))
                .props("outlined dense inputmode=numeric")
                .classes("w-full")
            )
            demo = ui.checkbox("This is a synthetic demo factor")
            ui.label("Demo factors are labelled in records and totals.").classes(
                "text-xs text-gray-500"
            )

            if factor:
                name.value = factor["name"]
                scope.value = factor["scope"]
                unit.value = factor["unit"]
                value.value = factor["kg_per_unit"]
                source.value = factor["source"]
                year.value = str(factor["year"])
                demo.value = factor["is_demo"]
                scope.disable()
                unit.disable()
                ui.label("Saving does not recalculate existing activities.").classes(
                    "text-amber-800"
                )

            async def save():
                save_button.disable()
                try:
                    ok, result = await call_api(
                        api.request(
                            "PATCH" if factor else "POST",
                            f"emissions/factors/{factor['id']}/"
                            if factor
                            else "emissions/factors/",
                            json={
                                "name": name.value,
                                "scope": scope.value,
                                "unit": unit.value,
                                "kg_per_unit": value.value,
                                "source": source.value,
                                "year": year.value,
                                "is_demo": demo.value,
                            },
                        ),
                        "Factor saved",
                    )
                    if ok:
                        dialog.close()
                        await self.load()
                finally:
                    save_button.enable()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps color=grey-8")
                save_button = ui.button("Save factor", on_click=save).props(
                    "unelevated no-caps color=teal-9"
                )
        dialog.open()

    def recalculate_dialog(self, factor):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl p-6 gap-4"):
            ui.label("Recalculate linked activities?").classes("text-xl font-semibold")
            ui.label(f"{factor['name']}: {factor['kg_per_unit']} kg CO₂e/{factor['unit']}")
            ui.label(
                "This applies the factor above to all linked company activities, across all dates "
                "and sites. Totals will change. Previous calculations remain in the audit log."
            )

            async def confirm():
                button.disable()
                try:
                    ok, result = await call_api(
                        api.post(
                            f"emissions/factors/{factor['id']}/recalculate/",
                            json={"factor": factor},
                        )
                    )
                    if ok:
                        dialog.close()
                        ui.notify(f"Recalculated {result['updated']} activities", type="positive")
                        self.page_number = 1
                        await self.load()
                finally:
                    button.enable()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                button = ui.button("Recalculate", on_click=confirm).props(
                    "unelevated no-caps color=teal-9"
                )
        dialog.open()

    def setup_needed_dialog(self, action):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md p-6"):
            ui.label(f"Before your first {action}").classes("text-xl font-semibold")
            if not self.factors:
                ui.label("Add an emission factor in the Emission factors tab.")
            if not self.sites:
                ui.label("Your company needs a site. Ask an administrator to add one.")
                ui.link("Go to Organisation", "/organisation")
            ui.button("Got it", on_click=dialog.close).props("flat no-caps color=teal-9")
        dialog.open()

    def import_dialog(self):
        if not self.factors or not self.sites:
            self.setup_needed_dialog("import")
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl p-6 gap-4"):
            ui.label("Import activities from CSV").classes("text-xl font-semibold")
            ui.label(
                "Required columns: date, description, site, factor, quantity, unit. "
                "Add factor_year when several factors share a name."
            ).classes("text-sm text-gray-600")
            ui.label(
                "Dates use YYYY-MM-DD. Site and factor names must match this company exactly. "
                "If any row is invalid, nothing is imported."
            ).classes("text-sm text-gray-600")
            ui.button(
                "Download template",
                icon="download",
                on_click=lambda: ui.download.content(CSV_TEMPLATE, "activity-template.csv"),
            ).props("flat no-caps color=teal-9")

            async def upload(event):
                try:
                    result = await api.post(
                        "emissions/activities/import/",
                        files={"file": (event.name, event.content.read(), "text/csv")},
                    )
                except api.ApiError as exc:
                    ui.notify(str(exc), type="negative", multi_line=True)
                    return
                ui.notify(f"Imported {result['created']} activities", type="positive")
                dialog.close()
                self.page_number = 1
                await self.load_records()

            ui.upload(on_upload=upload, auto_upload=True).props("accept=.csv flat").classes(
                "w-full"
            )
            with ui.row().classes("w-full justify-end"):
                ui.button("Close", on_click=dialog.close).props("flat no-caps color=grey-8")
        dialog.open()

    def activity_dialog(self, record=None):
        if not self.factors or not self.sites:
            self.setup_needed_dialog("activity")
            return
        factors = {f["id"]: dict(f) for f in self.factors}
        if record:
            factors[record["factor"]].update(
                kg_per_unit=record["factor_value"],
                unit=record["unit"],
                source=record["factor_source"],
                year=record["factor_year"],
                scope=record["scope"],
            )
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl p-6 gap-4"):
            ui.label("Edit activity" if record else "Record an activity").classes(
                "text-xl font-semibold"
            )
            ui.label("The selected factor determines the scope, unit and calculation.").classes(
                "text-sm text-gray-600"
            )
            description = (
                ui.input(
                    "Activity description",
                    value=record["description"] if record else "",
                    placeholder="e.g. October office electricity",
                )
                .props("outlined dense")
                .classes("w-full")
            )
            with ui.row().classes("w-full gap-3"):
                day = (
                    ui.input("Activity date", value=record["date"] if record else str(date.today()))
                    .props("type=date outlined dense")
                    .classes("grow")
                )
                site = (
                    ui.select(
                        {s["id"]: s["name"] for s in self.sites},
                        value=record["site"] if record else self.sites[0]["id"],
                        label="Site",
                    )
                    .props("outlined dense")
                    .classes("grow")
                )
            factor = (
                ui.select(
                    {
                        f["id"]: f"{f['name']} · {f['year']}" + (" · Demo" if f["is_demo"] else "")
                        for f in self.factors
                    },
                    value=record["factor"] if record else self.factors[0]["id"],
                    label="Emission factor",
                )
                .props("outlined dense")
                .classes("w-full")
            )
            department = (
                ui.select(
                    {0: "No department", **{d["id"]: d["name"] for d in self.departments}},
                    value=(record.get("department") or 0) if record else 0,
                    label="Department",
                )
                .classes("w-full")
                .props("outlined dense")
            )
            details = ui.label().classes("text-sm text-gray-600 break-all")
            quantity = (
                ui.input(
                    "Quantity", value=record["quantity"] if record else "", placeholder="e.g. 100"
                )
                .props("outlined dense inputmode=decimal")
                .classes("w-full")
            )
            preview = ui.label("Preview the calculation before saving.").classes(
                "w-full rounded-lg bg-emerald-50 p-4 text-emerald-900"
            )

            def inputs_changed():
                selected = factors[factor.value]
                quantity.set_label(f"Quantity ({selected['unit']})")
                details.set_text(
                    f"Scope {selected['scope']} · {number(selected['kg_per_unit'])} "
                    f"kg CO₂e/{selected['unit']} · {selected['source']} ({selected['year']})"
                )
                preview.set_text("Preview the calculation before saving.")

            def calculation_payload():
                return {
                    "factor": factor.value,
                    "quantity": quantity.value,
                    "unit": factors[factor.value]["unit"],
                    **({"activity": record["id"]} if record else {}),
                }

            async def calculate():
                preview_button.disable()
                inputs = calculation_payload()
                try:
                    ok, result = await call_api(api.post("emissions/preview/", json=inputs))
                    if ok and inputs == calculation_payload():
                        preview.set_text(f"Calculated emissions: {kg(result['kg_co2e'])}")
                finally:
                    preview_button.enable()

            async def save():
                save_button.disable()
                try:
                    data = calculation_payload() | {
                        "description": description.value,
                        "date": day.value,
                        "site": site.value,
                        "department": department.value or None,
                    }
                    operation = (
                        api.patch(f"emissions/activities/{record['id']}/", json=data)
                        if record
                        else api.post("emissions/activities/", json=data)
                    )
                    ok, result = await call_api(operation)
                    if ok:
                        dialog.close()
                        ui.notify(f"Activity saved · {kg(result['kg_co2e'])}", type="positive")
                        self.page_number = 1
                        await self.load_records()
                finally:
                    save_button.enable()

            factor.on_value_change(inputs_changed)
            quantity.on_value_change(inputs_changed)
            inputs_changed()
            with ui.row().classes("w-full justify-between gap-2"):
                preview_button = ui.button("Preview calculation", on_click=calculate).props(
                    "outline no-caps color=teal-9"
                )
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close).props("flat no-caps color=grey-8")
                    save_button = ui.button("Save activity", on_click=save).props(
                        "unelevated no-caps color=teal-9"
                    )
        dialog.open()

    def record_dialog(self, record):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl p-6 gap-3"):
            ui.label(record["description"]).classes("text-xl font-semibold")
            ui.label(f"{record['date']} · {record['site_name']} · Scope {record['scope']}").classes(
                "text-gray-600"
            )
            ui.label(kg(record["kg_co2e"])).classes("text-3xl font-semibold text-teal-900")
            ui.label(
                f"{number(record['quantity'])} {record['unit']} × "
                f"{number(record['factor_value'])} kg CO₂e/{record['unit']}"
            ).classes("text-base")
            ui.separator()
            ui.label(f"Factor: {record['category']}")
            ui.label(f"Source: {record['factor_source']} ({record['factor_year']})").classes(
                "break-all"
            )
            if record["is_demo"]:
                ui.label("Demo data · calculated with a synthetic factor.").classes(
                    "text-amber-800"
                )
            ui.label(
                "Rounded to 0.01 kg CO₂e. The factor inputs are preserved with this record."
            ).classes("text-sm text-gray-500")
            with ui.row().classes("w-full justify-end gap-2"):
                if self.can_edit:

                    def edit():
                        dialog.close()
                        self.activity_dialog(record)

                    def delete():
                        dialog.close()
                        self.delete_dialog(record)

                    ui.button("Edit activity", icon="edit", on_click=edit).props(
                        "outline no-caps color=teal-9"
                    )
                    ui.button("Delete activity", icon="delete", on_click=delete).props(
                        "flat no-caps color=negative"
                    )
                ui.button("Close", on_click=dialog.close).props("flat no-caps color=teal-9")
        dialog.open()

    def delete_dialog(self, record):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md p-6 gap-4"):
            ui.label("Delete this activity?").classes("text-xl font-semibold")
            ui.label(record["description"]).classes("font-medium")
            ui.label(f"{record['date']} · {kg(record['kg_co2e'])}")
            ui.label(
                "This removes the activity from company totals. Its details remain in the "
                "audit history, but this action cannot be undone here."
            ).classes("text-sm text-gray-600")

            async def confirm():
                delete_button.disable()
                try:
                    ok, _ = await call_api(
                        api.delete(f"emissions/activities/{record['id']}/"), "Activity deleted"
                    )
                    if ok:
                        dialog.close()
                        self.page_number = 1
                        await self.load_records()
                finally:
                    delete_button.enable()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps color=grey-8")
                delete_button = ui.button("Delete activity", on_click=confirm).props(
                    "unelevated no-caps color=negative"
                )
        dialog.open()
