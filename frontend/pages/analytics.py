"""Analytics dashboard: KPIs, charts, target progress and CSV/PDF export.

All numbers come from the backend (``/api/analytics/...``). This page only draws them.
"""

import base64

import plotly.graph_objects as go
from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import api, session
from frontend.components import call_api, kg, section_title
from frontend.layout import page_layout

SCOPES = {1: "Scope 1 · Direct", 2: "Scope 2 · Energy", 3: "Scope 3 · Indirect"}
# Blue, orange and teal differ in lightness too, so the scopes stay readable without colour.
SCOPE_COLOURS = {1: "#1f5f8b", 2: "#e08a2c", 3: "#2a9d8f"}
TARGET_STATUS = {
    "on_track": ("On track", "positive"),
    "at_risk": ("At risk", "warning"),
    "off_track": ("Off track", "negative"),
    "no_data": ("No data yet", "grey-7"),
}
CHART_LAYOUT = {
    "margin": {"l": 10, "r": 10, "t": 10, "b": 10},
    "height": 300,
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "Inter, Arial, sans-serif"},
}


# Chart builders are plain functions so they can be tested without a browser.
def scope_figure(by_scope):
    scopes = [1, 2, 3]
    return go.Figure(
        go.Pie(
            labels=[SCOPES[s] for s in scopes],
            values=[float(by_scope.get(str(s), 0)) for s in scopes],
            hole=0.55,
            marker={"colors": [SCOPE_COLOURS[s] for s in scopes]},
            sort=False,
            textinfo="percent",
            hovertemplate="%{label}<br>%{value:,.2f} kg CO2e<extra></extra>",
        ),
        layout=CHART_LAYOUT | {"legend": {"orientation": "h", "y": -0.1}},
    )


def trend_figure(trend):
    return go.Figure(
        go.Scatter(
            x=[row["month"] for row in trend],
            y=[float(row["kg_co2e"]) for row in trend],
            mode="lines+markers",
            line={"color": "#1f5f8b", "width": 3},
            hovertemplate="%{x}<br>%{y:,.2f} kg CO2e<extra></extra>",
        ),
        layout=CHART_LAYOUT
        | {"xaxis": {"type": "category"}, "yaxis": {"title": "kg CO2e", "rangemode": "tozero"}},
    )


def site_figure(by_site):
    rows = list(reversed(by_site))  # largest bar on top
    return go.Figure(
        go.Bar(
            x=[float(row["kg_co2e"]) for row in rows],
            y=[row["site"] for row in rows],
            orientation="h",
            marker={"color": "#2a9d8f"},
            hovertemplate="%{y}<br>%{x:,.2f} kg CO2e<extra></extra>",
        ),
        layout=CHART_LAYOUT | {"xaxis": {"title": "kg CO2e"}},
    )


def department_figure(by_department):
    rows = list(reversed(by_department))  # largest bar on top
    return go.Figure(
        go.Bar(
            x=[float(row["kg_co2e"]) for row in rows],
            y=[row["department"] for row in rows],
            orientation="h",
            marker={"color": "#1f5f8b"},
            hovertemplate="%{y}<br>%{x:,.2f} kg CO2e<extra></extra>",
        ),
        layout=CHART_LAYOUT | {"xaxis": {"title": "kg CO2e"}},
    )


@ui.page("/dashboard")
async def page():
    if not session.token():
        return RedirectResponse("/login")
    with page_layout("Analytics Dashboard"):
        screen = DashboardPage()
    await ui.context.client.connected()
    await screen.load()


class DashboardPage:
    def __init__(self):
        self.filters = {}
        ui.label("See where your emissions come from and how they change over time.").classes(
            "text-gray-600"
        )
        with ui.row().classes("w-full items-end gap-3"):
            self.start = ui.input("From").props("type=date outlined dense")
            self.end = ui.input("Before (exclusive)").props("type=date outlined dense")
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
            self.department = (
                ui.select(
                    {0: "All departments", "unassigned": "Unassigned"}, value=0, label="Department"
                )
                .props("outlined dense")
                .classes("w-44")
            )
            ui.button("Apply", on_click=self.apply_filters).props("unelevated color=teal-9 no-caps")
            ui.button("Reset", on_click=self.reset_filters).props("flat color=grey-8 no-caps")
            ui.space()
            ui.button("Export CSV", icon="download", on_click=self.export_csv).props(
                "outline color=teal-9 no-caps"
            )
            ui.button("Export PDF", icon="picture_as_pdf", on_click=self.export_pdf).props(
                "outline color=teal-9 no-caps"
            )
        self.content = ui.column().classes("w-full gap-4")
        with self.content:
            ui.label("Loading your dashboard…").classes("text-gray-500")

    async def load(self):
        ok, sites = await call_api(api.get("accounts/sites/"))
        if ok:
            self.site.set_options({0: "All sites", **{s["id"]: s["name"] for s in sites}})
        ok, departments = await call_api(api.get("accounts/departments/"))
        if ok:
            self.department.set_options(
                {0: "All departments", "unassigned": "Unassigned"}
                | {d["id"]: d["name"] for d in departments}
            )
        await self.refresh()

    async def apply_filters(self):
        self.filters = {
            key: value
            for key, value in {
                "start": self.start.value,
                "end": self.end.value,
                "scope": self.scope.value,
                "site": self.site.value,
                "department": self.department.value,
            }.items()
            if value
        }
        await self.refresh()

    async def reset_filters(self):
        self.start.value = self.end.value = ""
        self.scope.value = self.site.value = self.department.value = 0
        await self.apply_filters()

    async def refresh(self):
        ok, data = await call_api(api.get("analytics/dashboard/", params=self.filters))
        self.content.clear()
        with self.content:
            if not ok:
                ui.label("The dashboard could not be loaded. Check the filters.").classes(
                    "text-red-700"
                )
                return
            self.render(data)

    def render(self, data):
        self.kpi_row(data)
        if not data["record_count"]:
            with ui.card().classes("w-full items-center p-8"):
                ui.icon("insights", size="48px").classes("text-gray-400")
                ui.label("No activity records match these filters yet.").classes("text-gray-600")
                ui.link("Add emissions data", "/emissions")
            self.targets_card(data["targets"])
            return
        with ui.row().classes("w-full gap-4 no-wrap max-md:flex-wrap"):
            with ui.card().classes("flex-1 min-w-72"):
                section_title("Emissions by scope")
                ui.plotly(scope_figure(data["by_scope"])).classes("w-full")
            with ui.card().classes("flex-[2] min-w-72"):
                section_title("Monthly trend")
                ui.plotly(trend_figure(data["trend"])).classes("w-full")
        with ui.row().classes("w-full gap-4 no-wrap max-md:flex-wrap"):
            with ui.card().classes("flex-1 min-w-72"):
                section_title("Emissions by site")
                ui.plotly(site_figure(data["by_site"])).classes("w-full")
            with ui.card().classes("flex-1 min-w-72"):
                section_title("Emissions by department")
                ui.plotly(department_figure(data["by_department"])).classes("w-full")
        with ui.row().classes("w-full gap-4 no-wrap max-md:flex-wrap"):
            with ui.card().classes("w-full"):
                self.top_sources_table(data["top_sources"])
        self.targets_card(data["targets"])

    def kpi_row(self, data):
        largest = data["largest_scope"]
        score = data["sustainability_score"]
        score_value = (
            f"{float(score):.0f} / 100" if score is not None else "Set a target to get a score"
        )
        tiles = [
            ("Total emissions", kg(data["total_kg_co2e"]), "co2"),
            ("Activity records", str(data["record_count"]), "receipt_long"),
            ("Sites reporting", str(data["site_count"]), "apartment"),
            ("Largest scope", SCOPES[largest] if largest else "None yet", "donut_large"),
            ("Sustainability score", score_value, "eco"),
        ]
        with ui.row().classes("w-full gap-4 no-wrap max-md:flex-wrap"):
            for label, value, icon in tiles:
                with ui.card().classes("flex-1 min-w-48 bg-emerald-50 border border-emerald-100"):
                    with ui.row().classes("items-center gap-2 text-emerald-900"):
                        ui.icon(icon)
                        ui.label(label).classes("text-sm")
                    ui.label(value).classes("text-xl font-semibold")

    def top_sources_table(self, sources):
        section_title("Top emission sources")
        columns = [
            {"name": "category", "label": "Category", "field": "category", "align": "left"},
            {"name": "scope", "label": "Scope", "field": "scope"},
            {"name": "kg", "label": "kg CO2e", "field": "kg", "align": "right"},
            {"name": "share", "label": "Share", "field": "share", "align": "right"},
        ]
        rows = [
            {
                "category": row["category"],
                "scope": row["scope"],
                "kg": f"{float(row['kg_co2e']):,.2f}",
                "share": f"{float(row['share_percent']):.1f}%",
            }
            for row in sources
        ]
        ui.table(columns=columns, rows=rows, row_key="category").props("flat dense").classes(
            "w-full"
        )

    def targets_card(self, targets):
        with ui.card().classes("w-full"):
            section_title("Reduction targets")
            if not targets:
                ui.label("No targets set yet. Admins can add them on the Organisation page.")
                return
            for target in targets:
                text, colour = TARGET_STATUS.get(target["status"], (target["status"], "grey-7"))
                achieved = max(0.0, float(target["reduction_achieved_percent"]))
                with ui.row().classes("w-full items-center gap-4"):
                    ui.label(target["label"]).classes("min-w-60")
                    ui.linear_progress(
                        value=min(achieved / 100, 1), show_value=False, size="10px"
                    ).props(f"color={colour} rounded").classes("flex-1")
                    ui.badge(text, color=colour)
                ui.label(
                    f"{target['reporting_year']}: projected {kg(target['projected_kg_co2e'])}, "
                    f"target {kg(target['target_kg_co2e'])}"
                ).classes("text-sm text-gray-600")

    async def export_csv(self):
        ok, data = await call_api(api.get("analytics/export/csv/", params=self.filters))
        if ok:
            ui.download(data["content"].encode("utf-8"), data["filename"], "text/csv")
            ui.notify(f"Exported {data['rows']} records.", type="positive")

    async def export_pdf(self):
        ok, data = await call_api(api.get("analytics/export/pdf/", params=self.filters))
        if ok:
            ui.download(
                base64.b64decode(data["content_base64"]), data["filename"], "application/pdf"
            )
            ui.notify("PDF report exported.", type="positive")
