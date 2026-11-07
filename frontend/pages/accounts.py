from datetime import date

from fastapi.responses import RedirectResponse
from nicegui import ui

from frontend import api, session
from frontend.components import call_api, kg, section_title
from frontend.layout import page_layout

ROLES = {"admin": "Administrator", "editor": "Editor", "viewer": "Viewer"}
SCOPES = {"all": "All scopes", "1": "Scope 1", "2": "Scope 2", "3": "Scope 3"}
STATUS = {
    "no_data": ("No data yet", "grey"),
    "on_track": ("On track", "positive"),
    "at_risk": ("At risk", "warning"),
    "off_track": ("Off track", "negative"),
}
ALERT_COLOURS = {"info": "blue", "warning": "orange", "critical": "red"}


@ui.page("/organisation")
async def page():
    if not session.token():
        return RedirectResponse("/login")
    is_admin = session.is_admin()

    with page_layout("Users, Organisation & Targets"):
        with ui.tabs().classes("w-full") as tabs:
            tab_names = ["Organisation", "Team", "Targets", "Alerts"]
            if is_admin:
                tab_names.append("Audit log")
            tab_list = [ui.tab(name) for name in tab_names]
        boxes = {}
        with ui.tab_panels(tabs, value=tab_list[0]).classes("w-full"):
            for name, tab in zip(tab_names, tab_list):
                with ui.tab_panel(tab):
                    boxes[name] = ui.column().classes("w-full gap-4")

    sections = {
        "Organisation": lambda: organisation_section(boxes["Organisation"], is_admin),
        "Team": lambda: team_section(boxes["Team"], is_admin),
        "Alerts": lambda: alerts_section(boxes["Alerts"]),
    }
    sections["Targets"] = lambda: targets_section(boxes["Targets"], is_admin, sections["Alerts"])
    if is_admin:
        sections["Audit log"] = lambda: audit_section(boxes["Audit log"])

    await ui.context.client.connected()
    for load in sections.values():
        await load()


# Organisation details and sites ----------------------------------------------


async def organisation_section(box, is_admin):
    ok, org = await call_api(api.get("accounts/organisation/"))
    ok_sites, sites = await call_api(api.get("accounts/sites/"))
    if not (ok and ok_sites):
        return
    reload = lambda: organisation_section(box, is_admin)  # noqa: E731
    box.clear()
    with box:
        with ui.card().classes("w-full"):
            section_title("Company details")
            name = ui.input("Company name", value=org["name"])
            industry = ui.input("Industry", value=org["industry"])
            country = ui.input("Country", value=org["country"])
            employees = ui.number("Employees", value=org["employee_count"], min=0, precision=0)
            for field in (name, industry, country, employees):
                field.classes("w-full")
                if not is_admin:
                    field.disable()

            async def save():
                count = employees.value
                payload = {
                    "name": name.value,
                    "industry": industry.value,
                    "country": country.value,
                    "employee_count": None if count is None else int(count),
                }
                ok, _ = await call_api(
                    api.patch("accounts/organisation/", json=payload), "Company details saved"
                )
                if ok:
                    await reload()

            if is_admin:
                ui.button("Save", on_click=save)

        with ui.card().classes("w-full"):
            section_title("Sites and business units")
            if not sites:
                ui.label("No sites added yet.").classes("text-gray-500")
            for site in sites:
                with ui.row().classes("w-full items-center"):
                    ui.icon("apartment")
                    ui.label(site["name"]).classes("font-medium")
                    ui.label(site["location"]).classes("text-gray-500")
                    ui.space()
                    if is_admin:

                        async def remove(site_id=site["id"]):
                            ok, _ = await call_api(
                                api.delete(f"accounts/sites/{site_id}/"), "Site removed"
                            )
                            if ok:
                                await reload()

                        ui.button(icon="delete", on_click=remove).props("flat round dense")
            if is_admin:
                with ui.row().classes("w-full items-end"):
                    site_name = ui.input("New site name")
                    location = ui.input("Location")

                    async def add_site():
                        payload = {"name": site_name.value, "location": location.value}
                        ok, _ = await call_api(
                            api.post("accounts/sites/", json=payload), "Site added"
                        )
                        if ok:
                            await reload()

                    ui.button("Add site", on_click=add_site)

        ok_departments, departments = await call_api(api.get("accounts/departments/"))
        if not ok_departments:
            return
        with ui.card().classes("w-full"):
            section_title("Departments")
            if not departments:
                ui.label("No departments added yet.").classes("text-gray-500")
            for department in departments:
                with ui.row().classes("w-full items-center"):
                    ui.icon("apartment")
                    ui.label(department["name"]).classes("font-medium")
                    ui.label(department["location"]).classes("text-gray-500")
                    ui.space()
                    if is_admin:

                        async def remove(department_id=department["id"]):
                            ok, _ = await call_api(
                                api.delete(f"accounts/departments/{department_id}/"),
                                "Department removed",
                            )
                            if ok:
                                await reload()

                        ui.button(icon="delete", on_click=remove).props("flat round dense")
            if is_admin:
                with ui.row().classes("w-full items-end"):
                    department_name = ui.input("New department name")
                    department_location = ui.input("Location")

                    async def add_department():
                        payload = {
                            "name": department_name.value,
                            "location": department_location.value,
                        }
                        ok, _ = await call_api(
                            api.post("accounts/departments/", json=payload), "Department added"
                        )
                        if ok:
                            await reload()

                    ui.button("Add department", on_click=add_department)


# Team -----------------------------------------------------------------------------


async def team_section(box, is_admin):
    ok, members = await call_api(api.get("accounts/members/"))
    if not ok:
        return
    reload = lambda: team_section(box, is_admin)  # noqa: E731
    me = session.user().get("id")
    box.clear()
    with box:
        with ui.card().classes("w-full"):
            section_title("Members")
            for member in members:
                with ui.row().classes("w-full items-center"):
                    ui.icon("person" if member["is_active"] else "person_off")
                    full_name = f"{member['first_name']} {member['last_name']}".strip()
                    ui.label(member["username"]).classes("font-medium")
                    ui.label(full_name or member["email"]).classes("text-gray-500")
                    if not member["is_active"]:
                        ui.badge("deactivated", color="grey")
                    ui.space()
                    if not is_admin:
                        ui.label(ROLES[member["role"]])
                        continue

                    async def change(event, member_id=member["id"]):
                        await update_member(member_id, {"role": event.value}, reload)

                    ui.select(ROLES, value=member["role"], on_change=change).classes("w-40")
                    if member["id"] == me:
                        continue
                    if member["is_active"]:

                        async def deactivate(member_id=member["id"]):
                            ok, _ = await call_api(
                                api.delete(f"accounts/members/{member_id}/"),
                                "Member deactivated",
                            )
                            if ok:
                                await reload()

                        ui.button("Deactivate", on_click=deactivate).props("flat color=negative")
                    else:

                        async def reactivate(member_id=member["id"]):
                            await update_member(member_id, {"is_active": True}, reload)

                        ui.button("Reactivate", on_click=reactivate).props("flat")

        if is_admin:
            with ui.card().classes("w-full"):
                section_title("Add a member")
                with ui.row().classes("w-full items-end"):
                    username = ui.input("Username")
                    email = ui.input("Email")
                    password = ui.input("Initial password", password=True)
                    role = ui.select(ROLES, value="viewer", label="Role").classes("w-40")

                    async def add_member():
                        payload = {
                            "username": username.value,
                            "email": email.value,
                            "password": password.value,
                            "role": role.value,
                        }
                        ok, _ = await call_api(
                            api.post("accounts/members/", json=payload), "Member added"
                        )
                        if ok:
                            await reload()

                    ui.button("Add member", on_click=add_member)


async def update_member(member_id, payload, reload):
    await call_api(api.patch(f"accounts/members/{member_id}/", json=payload), "Member updated")
    await reload()  # Also restores the previous value after a rejected change.


# Targets ---------------------------------------------------------------------------


async def targets_section(box, is_admin, reload_alerts):
    ok, targets = await call_api(api.get("accounts/targets/"))
    if not ok:
        return
    reload = lambda: targets_section(box, is_admin, reload_alerts)  # noqa: E731
    box.clear()
    with box:
        with ui.row().classes("w-full items-center"):
            section_title("Yearly reduction targets")
            ui.space()

            async def evaluate():
                ok, alerts = await call_api(api.post("accounts/targets/evaluate/"))
                if ok:
                    ui.notify(f"Targets checked: {len(alerts)} new alert(s).")
                    await reload_alerts()

            ui.button("Check targets", icon="fact_check", on_click=evaluate).props("outline")

        if not targets:
            ui.label("No targets set yet.").classes("text-gray-500")
        for target in targets:
            target_card(target, is_admin, reload)

        if is_admin:
            add_target_form(reload)


def target_card(target, is_admin, reload):
    progress = target["progress"]
    label, colour = STATUS[progress["status"]]
    with ui.card().classes("w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label(
                f"{SCOPES[target['scope']]}: -{float(target['reduction_percent']):g}% "
                f"by {target['target_year']}"
            ).classes("text-base font-medium")
            ui.badge(label, color=colour)
            ui.space()
            if is_admin:

                async def remove():
                    ok, _ = await call_api(
                        api.delete(f"accounts/targets/{target['id']}/"), "Target deleted"
                    )
                    if ok:
                        await reload()

                ui.button(icon="delete", on_click=remove).props("flat round dense")
        ui.label(
            f"Baseline {target['baseline_year']}: {kg(target['baseline_kg_co2e'])} → "
            f"target {kg(target['target_kg_co2e'])}"
        ).classes("text-gray-600")
        if progress["status"] != "no_data":
            ui.label(
                f"{progress['reporting_year']}: projected {kg(progress['projected_kg_co2e'])}, "
                f"expected on the path {kg(progress['expected_kg_co2e'])}"
            )
            achieved = max(0.0, float(progress["reduction_achieved_percent"]))
            share = min(1.0, achieved / float(target["reduction_percent"]))
            ui.linear_progress(value=share, show_value=False, color=colour).classes("mt-2")
            ui.label(f"{achieved:.1f}% reduced of {float(target['reduction_percent']):g}% goal")


def add_target_form(reload):
    this_year = date.today().year
    with ui.card().classes("w-full"):
        section_title("Add a target")
        with ui.row().classes("w-full items-end"):
            scope = ui.select(SCOPES, value="all", label="Scope").classes("w-36")
            baseline_year = ui.number("Baseline year", value=this_year - 1, precision=0)
            baseline_kg = ui.number("Baseline kg CO2e", min=0)
            target_year = ui.number("Target year", value=this_year + 5, precision=0)
            percent = ui.number("Reduction %", value=30, min=0, max=100)

            async def add():
                if baseline_kg.value is None or percent.value is None:
                    ui.notify("Enter the baseline emissions and reduction.", type="warning")
                    return
                payload = {
                    "scope": scope.value,
                    "baseline_year": int(baseline_year.value or 0),
                    "baseline_kg_co2e": str(baseline_kg.value),
                    "target_year": int(target_year.value or 0),
                    "reduction_percent": str(percent.value),
                }
                ok, _ = await call_api(api.post("accounts/targets/", json=payload), "Target added")
                if ok:
                    await reload()

            ui.button("Add target", on_click=add)


# Alerts and audit log --------------------------------------------------------------


async def alerts_section(box):
    ok, alerts = await call_api(api.get("accounts/alerts/"))
    if not ok:
        return
    reload = lambda: alerts_section(box)  # noqa: E731
    box.clear()
    with box:
        with ui.row().classes("w-full items-center"):
            section_title("Alerts")
            ui.space()

            async def read_all():
                ok, _ = await call_api(api.post("accounts/alerts/read-all/"))
                if ok:
                    await reload()

            if any(not alert["is_read"] for alert in alerts):
                ui.button("Mark all as read", on_click=read_all).props("flat")
        if not alerts:
            ui.label("No alerts. Use “Check targets” to evaluate your targets.").classes(
                "text-gray-500"
            )
        for alert in alerts:
            with ui.card().classes("w-full" + (" opacity-60" if alert["is_read"] else "")):
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.icon("warning", color=ALERT_COLOURS[alert["level"]])
                    ui.label(alert["message"]).classes("grow")
                    ui.label(alert["created_at"][:10]).classes("text-gray-500 text-sm")
                    if not alert["is_read"]:

                        async def read(alert_id=alert["id"]):
                            ok, _ = await call_api(api.post(f"accounts/alerts/{alert_id}/read/"))
                            if ok:
                                await reload()

                        ui.button(icon="done", on_click=read).props("flat round dense")


async def audit_section(box, page_number=1):
    ok, data = await call_api(api.get("accounts/audit-log/", params={"page": page_number}))
    if not ok:
        return
    box.clear()
    with box:
        section_title("Audit history")
        rows = [
            {
                "id": entry["id"],
                "when": entry["created_at"][:19].replace("T", " "),
                "actor": entry["actor"] or "—",
                "action": entry["action"],
                "object": f"{entry['object_type']} {entry['object_repr']}".strip(),
                "changes": ", ".join(
                    f"{field}: {change['from']} → {change['to']}"
                    for field, change in entry["changes"].items()
                ),
            }
            for entry in data["results"]
        ]
        columns = [
            {"name": key, "label": key.title(), "field": key, "align": "left"}
            for key in ("when", "actor", "action", "object", "changes")
        ]
        ui.table(rows=rows, columns=columns, row_key="id").classes("w-full")
        with ui.row():
            if data["previous"]:
                ui.button("Newer", on_click=lambda: audit_section(box, page_number - 1))
            if data["next"]:
                ui.button("Older", on_click=lambda: audit_section(box, page_number + 1))
