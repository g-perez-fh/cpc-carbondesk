"""Validate activity rows from a CSV file without touching the database.

The view passes in the company's sites and factors, and the service layer saves
the accepted rows. Keeping the parsing here makes it possible to test the rules
without Django models or HTTP requests.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .calculations import CO2eCalculator, EmissionsError

REQUIRED_COLUMNS = ("date", "description", "site", "factor", "quantity", "unit")
MAX_ROWS = 5000


@dataclass(frozen=True)
class ImportedActivity:
    """One CSV row that passed validation and is ready to save."""

    row_number: int
    date: date
    description: str
    site: object
    factor: object
    quantity: Decimal
    unit: str
    department: object = None


class CsvImporter:
    """Parse and validate activity rows from CSV text.

    ``sites_by_name`` and ``factors_by_name`` map a company's exact names to
    lists of objects. A list is used so ambiguous names are reported instead of
    silently choosing one record.
    """

    def __init__(
        self, text, *, sites_by_name, factors_by_name, departments_by_name=None, today=None
    ):
        self._departments_by_name = departments_by_name or {}
        self.set_text(text)
        self._sites_by_name = sites_by_name
        self._factors_by_name = factors_by_name
        self._today = today or date.today()

    def get_text(self):
        return self._text

    def set_text(self, text):
        if not isinstance(text, str):
            raise EmissionsError("CSV input must be text.")
        self._text = text

    def parse(self):
        """Return ``(activities, errors)``; saving is the caller's responsibility."""
        try:
            reader = csv.DictReader(io.StringIO(self._text), strict=True)
            if not reader.fieldnames:
                return [], [self._error(1, "The file is empty.")]
            headers = self._normalise_headers(reader.fieldnames)
            if headers is None:
                return [], [self._error(1, "The header contains duplicate columns.")]
            missing = [name for name in REQUIRED_COLUMNS if name not in headers.values()]
            if missing:
                return [], [self._error(1, f"Missing required column(s): {', '.join(missing)}.")]

            activities = []
            errors = []
            row_count = 0
            for row in reader:
                row_count += 1
                if row_count > MAX_ROWS:
                    errors.append(
                        self._error(
                            reader.line_num,
                            f"Only the first {MAX_ROWS} rows can be imported.",
                        )
                    )
                    break
                values = self._normalise_row(row, headers)
                if values is None:
                    errors.append(
                        self._error(reader.line_num, "This row has more values than the header.")
                    )
                    continue
                if not any(values.values()):
                    continue
                activity, row_errors = self._parse_row(reader.line_num, values)
                if activity is not None:
                    activities.append(activity)
                errors.extend(row_errors)
        except csv.Error as exc:
            return [], [self._error(1, f"The file is not valid CSV: {exc}.")]

        if not activities and not errors:
            return [], [self._error(1, "The file has no activity rows.")]
        return activities, errors

    @staticmethod
    def _normalise_headers(fieldnames):
        normalised = [name.strip().lower().replace(" ", "_") for name in fieldnames]
        if len(set(normalised)) != len(normalised):
            return None
        return {raw: name for raw, name in zip(fieldnames, normalised)}

    @staticmethod
    def _normalise_row(row, headers):
        if None in row:
            return None
        return {headers[key]: (value or "").strip() for key, value in row.items() if key in headers}

    def _parse_row(self, row_number, values):
        errors = []
        department = None
        department_name = values.get("department", "")
        if department_name:
            department = self._departments_by_name.get(department_name)
            if department is None:
                errors.append("Department was not found in this company.")

        description = values.get("description", "")
        if not description:
            errors.append("A description is required.")
        elif len(description) > 160:
            errors.append("The description must be 160 characters or fewer.")

        activity_date = None
        raw_date = values.get("date", "")
        if not raw_date:
            errors.append("A date is required.")
        else:
            try:
                activity_date = date.fromisoformat(raw_date)
            except ValueError:
                errors.append("Use a date in YYYY-MM-DD format.")
            else:
                if activity_date > self._today:
                    errors.append("Activity dates cannot be in the future.")
                    activity_date = None

        site, site_error = self._match_site(values.get("site", ""))
        if site_error:
            errors.append(site_error)

        factor, factor_error = self._match_factor(
            values.get("factor", ""), values.get("factor_year", "")
        )
        if factor_error:
            errors.append(factor_error)

        quantity, quantity_error = self._parse_quantity(values.get("quantity", ""))
        if quantity_error:
            errors.append(quantity_error)

        unit = values.get("unit", "")
        if not unit:
            errors.append("A unit is required.")
        elif factor is not None and unit != factor.unit:
            errors.append(f"Unit '{unit}' does not match the factor unit '{factor.unit}'.")

        if errors:
            return None, [self._error(row_number, message) for message in errors]

        try:
            CO2eCalculator(factor.kg_per_unit, factor.unit).calculate(quantity, unit)
        except EmissionsError as exc:
            return None, [self._error(row_number, str(exc))]

        return (
            ImportedActivity(
                row_number=row_number,
                department=department,
                date=activity_date,
                description=description,
                site=site,
                factor=factor,
                quantity=quantity,
                unit=unit,
            ),
            [],
        )

    def _match_site(self, name):
        if not name:
            return None, "A site is required."
        matches = self._sites_by_name.get(name, [])
        if not matches:
            return None, f"Site '{name}' was not found in this company."
        if len(matches) > 1:
            return None, f"Site '{name}' is ambiguous; give the sites unique names."
        return matches[0], None

    def _match_factor(self, name, raw_year):
        if not name:
            return None, "A factor is required."
        matches = list(self._factors_by_name.get(name, []))
        if raw_year:
            try:
                year = int(raw_year)
            except ValueError:
                return None, "factor_year must be a whole year such as 2026."
            matches = [factor for factor in matches if factor.year == year]
            if not matches:
                return None, f"Factor '{name}' for {year} was not found in this company."
        if not matches:
            return None, f"Factor '{name}' was not found in this company."
        if len(matches) > 1:
            return None, f"Factor '{name}' matches several versions; add a factor_year column."
        return matches[0], None

    @staticmethod
    def _parse_quantity(value):
        if not value:
            return None, "A quantity is required."
        try:
            quantity = Decimal(value)
        except (InvalidOperation, ValueError):
            return None, "Enter a valid quantity."
        if not quantity.is_finite() or quantity < 0:
            return None, "Quantity must be a finite, non-negative number."
        if quantity >= Decimal("10000000000"):
            return None, "Quantity is too large."
        if quantity != quantity.quantize(Decimal("0.0001")):
            return None, "Quantity can have at most four decimal places."
        return quantity, None

    @staticmethod
    def _error(row_number, message):
        return {"row": row_number, "message": message}
