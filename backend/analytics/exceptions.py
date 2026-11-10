"""Analytics-specific errors, each carrying the HTTP status its view should return."""


class AnalyticsError(Exception):
    """Base class for analytics errors. Subclasses set error_code, status_code, default_message."""

    error_code = "analytics_error"
    status_code = 400
    default_message = "Analytics error."

    def __init__(self, message=None):
        self.message = message or self.default_message
        super().__init__(self.message)

    def as_response_data(self):
        return {"error": self.error_code, "detail": self.message}


class InvalidFilterError(AnalyticsError):
    """The requested filters (scope, date range, site) are not usable."""

    error_code = "invalid_filter"
    status_code = 400
    default_message = "These filters are not valid."


class NoDataError(AnalyticsError):
    """No activity records matched the given filters."""

    error_code = "no_data"
    status_code = 404
    default_message = "No activity records matched these filters."


class ExportError(AnalyticsError):
    """The requested report could not be exported, e.g. an unsupported format."""

    error_code = "export_error"
    status_code = 400
    default_message = "This report could not be exported."
