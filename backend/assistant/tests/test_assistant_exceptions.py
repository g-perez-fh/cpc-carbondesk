"""Assistant exceptions: the classes themselves, and how services and views use them."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from assistant import llm, services
from assistant.context import build_snapshot
from assistant.exceptions import (
    AIServiceUnavailableError,
    AssistantError,
    EmptyMessageError,
    InvalidPeriodError,
)
from assistant.models import Message
from assistant.views import ConversationViewSet

# The classes (no database) -------------------------------------------------------------


def test_base_error_uses_default_or_custom_message():
    assert AssistantError().message == "The assistant could not handle this request."
    assert str(AssistantError("custom")) == "custom"


@pytest.mark.parametrize(
    "cls, status, code",
    [
        (EmptyMessageError, 400, "empty_message"),
        (InvalidPeriodError, 400, "invalid_period"),
        (AIServiceUnavailableError, 503, "ai_unavailable"),
    ],
)
def test_subclasses_carry_status_and_code(cls, status, code):
    error = cls()
    assert isinstance(error, AssistantError)
    assert error.status_code == status
    assert error.as_response_data()["error"] == code


def test_empty_message_names_its_field():
    assert EmptyMessageError().as_response_data()["field"] == "content"
    assert "field" not in InvalidPeriodError().as_response_data()


# Services ----------------------------------------------------------------------------------


def test_llm_raises_ai_service_error_without_key():
    with pytest.raises(AIServiceUnavailableError):
        llm.complete("instructions", [{"role": "user", "content": "hi"}])


def test_send_message_rejects_empty_text_without_saving(viewer_user):
    conversation = services.start_conversation(viewer_user)
    with pytest.raises(EmptyMessageError):
        services.send_message(conversation, "   ")
    assert not Message.objects.exists()


def test_chat_falls_back_when_ai_service_errors(viewer_user, emissions):
    conversation = services.start_conversation(viewer_user)
    with patch("assistant.services.llm.complete", side_effect=AIServiceUnavailableError()):
        _, answer = services.send_message(conversation, "Hello")
    assert "data overview" in answer.content


def test_summary_for_future_month_raises(organisation):
    next_month = date.today().replace(day=1) + timedelta(days=32)
    with pytest.raises(InvalidPeriodError):
        services.generate_monthly_summary(organisation, next_month)


@pytest.mark.parametrize("year", [1, 9999])
def test_snapshot_rejects_unsupported_years(organisation, year):
    with pytest.raises(InvalidPeriodError):
        build_snapshot(organisation, year=year)


# Views --------------------------------------------------------------------------------------


def test_view_returns_json_error_for_assistant_error(api_for, viewer_user):
    client = api_for(viewer_user)
    conversation = client.post("/api/assistant/conversations/", {}).json()
    url = f"/api/assistant/conversations/{conversation['id']}/messages/"
    with patch.object(ConversationViewSet, "get_object", side_effect=AIServiceUnavailableError()):
        response = client.post(url, {"content": "hi"})
    assert response.status_code == 503
    assert response.json() == {
        "error": "ai_unavailable",
        "detail": AIServiceUnavailableError.default_message,
    }
