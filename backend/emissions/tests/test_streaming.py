from decimal import Decimal

import pytest

from emissions.calculations import EmissionsError
from emissions.streaming import ActivityStream, EmissionTransformer, ScopeFilter


def test_lazy_pipeline_and_tonnes():
    event = {"scope": 2, "factor": "power", "quantity": "100", "unit": "kWh"}
    factors = {"power": {"scope": 2, "kg_per_unit": "0.4", "unit": "kWh"}}
    stream = ActivityStream([dict(event, scope=1), event])
    pipeline = ScopeFilter([2]) + EmissionTransformer(factors)
    result = list(pipeline.run(stream))
    assert result[0]["tonnes_co2e"] == Decimal("0.04")
    assert len(result) == 1
    with pytest.raises(StopIteration):
        next(stream)
    assert "tonnes_co2e" not in event


def test_stream_rejects_invalid_scope():
    with pytest.raises(EmissionsError):
        ScopeFilter([4])
    with pytest.raises(EmissionsError):
        ScopeFilter([1]).process({})


def test_stream_rejects_missing_factor():
    with pytest.raises(EmissionsError):
        EmissionTransformer({}).process({"factor": "missing"})


def test_scope_setter_preserves_state_after_invalid_update():
    processor = ScopeFilter([2])
    with pytest.raises(EmissionsError):
        processor.set_scopes([4])
    copy = processor.get_scopes()
    copy.add(1)
    assert processor.get_scopes() == {2}


def test_csv_text_accessors():
    from emissions.csv_import import CsvImporter

    importer = CsvImporter("original", sites_by_name={}, factors_by_name={})
    importer.set_text("replacement")
    with pytest.raises(EmissionsError):
        importer.set_text(None)
    assert importer.get_text() == "replacement"
