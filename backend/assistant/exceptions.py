"""AI Sustainability Assistant errors, each carrying the HTTP status its view should return."""


class AssistantError(Exception):
    """Base class for assistant errors. Subclasses set error_code, status_code, default_message.

    ``field`` names the request field the error belongs to, if any.
    """

    error_code = "assistant_error"
    status_code = 400
    default_message = "The assistant could not handle this request."
    field = None

    def __init__(self, message=None):
        self.message = message or self.default_message
        super().__init__(self.message)

    def as_response_data(self):
        data = {"error": self.error_code, "detail": self.message}
        if self.field:
            data["field"] = self.field
        return data


class EmptyMessageError(AssistantError):
    """A chat message contains no text."""

    error_code = "empty_message"
    status_code = 400
    default_message = "Please enter a question for the assistant."
    field = "content"


class InvalidPeriodError(AssistantError):
    """The requested year or month cannot be analysed, e.g. a summary for a future month."""

    error_code = "invalid_period"
    status_code = 400
    default_message = "This period cannot be analysed."


class AIServiceUnavailableError(AssistantError):
    """The language model is not configured or did not answer.

    Chat and summaries catch this and fall back to rule-based answers, so users still
    get a reply; the 503 status applies if it ever reaches a view.
    """

    error_code = "ai_unavailable"
    status_code = 503
    default_message = "The AI service is unavailable right now."
