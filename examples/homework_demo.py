"""Run with PYTHONPATH=backend python examples/homework_demo.py."""

from emissions.calculations import CO2eCalculator
from emissions.csv_import import CsvImporter
from emissions.streaming import ActivityStream, EmissionTransformer, ScopeFilter

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
    {"scope": 1, "factor": "filtered", "quantity": "50", "unit": "l"},
    {"scope": 2, "factor": "demo", "quantity": "100", "unit": "kWh"},
]
pipeline = filter_step + EmissionTransformer(factors)
for result in pipeline.run(ActivityStream(events)):
    print("Stream result:", result["tonnes_co2e"], "tonnes CO2e")
