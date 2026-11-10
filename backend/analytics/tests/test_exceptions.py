"""Plain-Python tests for the analytics exception classes. No Django, no database."""

from analytics.exceptions import AnalyticsError, ExportError, InvalidFilterError, NoDataError


def test_analytics_error_uses_default_message():
    error = AnalyticsError()
    assert error.message == "Analytics error."
    assert error.status_code == 400


def test_analytics_error_accepts_a_custom_message():
    error = AnalyticsError("custom message")
    assert error.message == "custom message"
    assert str(error) == "custom message"


def test_invalid_filter_error_defaults():
    error = InvalidFilterError()
    assert error.status_code == 400
    assert error.as_response_data() == {
        "error": "invalid_filter",
        "detail": "These filters are not valid.",
    }


def test_no_data_error_defaults():
    error = NoDataError()
    assert error.status_code == 404
    assert error.as_response_data()["error"] == "no_data"


def test_export_error_defaults():
    error = ExportError()
    assert error.status_code == 400
    assert error.as_response_data()["error"] == "export_error"


def test_each_subclass_is_an_analytics_error():
    for cls in (InvalidFilterError, NoDataError, ExportError):
        assert issubclass(cls, AnalyticsError)
