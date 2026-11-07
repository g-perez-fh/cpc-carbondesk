"""Run with PYTHONPATH=backend:. python examples/homework_demo.py."""

from datetime import datetime
from decimal import Decimal

from emissions.calculations import CO2eCalculator
from emissions.csv_import import CsvImporter
from emissions.streaming import ActivityStream, EmissionTransformer, ScopeFilter
from stream_processing.base import ActivityEvent

calculator = CO2eCalculator("0.4", "kWh")
calculator.set_factor("0.4", "kWh")
print("Factor:", calculator.get_factor(), "Unit:", calculator.get_unit())
print("Result:", calculator.calculate("100", "kWh"), "kg CO2e (synthetic)")
importer = CsvImporter("", sites_by_name={}, factors_by_name={})
importer.set_text("date,description,site,factor,quantity,unit\n")
print("CSV input:", importer.get_text().strip())
print("CSV validation:", importer.parse()[1])
filter_step = ScopeFilter([1, 2])
filter_step.set_scopes([2])
print("Selected scopes:", filter_step.get_scopes())
factors = {"demo": {"scope": 2, "kg_per_unit": "0.4", "unit": "kWh"}}
events = [
    ActivityEvent(
        event_id=str(scope),
        source="synthetic",
        timestamp=datetime(2026, 1, 1),
        scope=scope,
        category="demo",
        quantity=Decimal("100"),
        unit="kWh",
    )
    for scope in [1, 2]
]
pipeline = ActivityStream(events) | filter_step | EmissionTransformer(factors)
for result in pipeline:
    print("Stream result:", result.tco2e, "tonnes CO2e")
