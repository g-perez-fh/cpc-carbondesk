from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from accounts.models import Organisation, User
from assistant import llm, services
from assistant.models import Conversation, MonthlySummary
from assistant.recommendations import recommend

pytestmark = pytest.mark.django_db


# Recommendations ----------------------------------------------------------------


def test_recommendations_are_ranked_by_savings():
    recs = recommend({1: Decimal("1000"), 2: Decimal("2000"), 3: Decimal("0")}, limit=3)
    assert [r.key for r in recs] == [
        "renewable_electricity",
        "fleet_electrification",
        "efficient_lighting",
    ]
    assert recs[0].estimated_savings_kg_co2e == Decimal("1400.00")
    assert all(r.scope != 3 for r in recs)


def test_no_recommendations_without_data():
    assert recommend({1: Decimal("0"), 2: Decimal("0"), 3: Decimal("0")}) == []


def test_recommendations_endpoint(api_for, viewer_user, emissions):
    emissions[3] = Decimal("1000")
    body = api_for(viewer_user).get("/api/assistant/recommendations/?year=2026").json()
    assert body["total"] == "1000"
    assert body["recommendations"][0]["key"] == "travel_policy"
    assert body["recommendations"][0]["estimated_savings_kg_co2e"] == "150.00"
    assert api_for(viewer_user).get("/api/assistant/recommendations/?year=abc").status_code == 400


@pytest.mark.parametrize("year", ["10000", "9999", "1", "0", "-1", "abc", "", "2026.5"])
def test_recommendations_reject_invalid_year_before_loading_data(api_for, viewer_user, year):
    with patch("assistant.views.build_snapshot") as build_snapshot:
        response = api_for(viewer_user).get("/api/assistant/recommendations/", {"year": year})
    assert response.status_code == 400
    assert "year" in response.json()
    build_snapshot.assert_not_called()


@pytest.mark.parametrize("year", [2, 2026, 9998])
def test_recommendations_accept_supported_years(api_for, viewer_user, year):
    response = api_for(viewer_user).get("/api/assistant/recommendations/", {"year": year})
    assert response.status_code == 200
    assert response.json()["year"] == year


def test_recommendations_default_to_current_year(api_for, viewer_user):
    response = api_for(viewer_user).get("/api/assistant/recommendations/")
    assert response.status_code == 200
    assert response.json()["year"] == date.today().year


# Chat --------------------------------------------------------------------------------


def test_chat_without_ai_key_answers_from_data(api_for, viewer_user, emissions):
    emissions.update({1: Decimal("100"), 2: Decimal("900")})
    client = api_for(viewer_user)
    conversation = client.post("/api/assistant/conversations/", {}).json()

    response = client.post(
        f"/api/assistant/conversations/{conversation['id']}/messages/",
        {"content": "How can we reduce emissions?"},
    )
    assert response.status_code == 201
    answer = response.json()["answer"]["content"]
    assert "1,000.00 kg CO2e" in answer
    assert "Switch to renewable electricity" in answer

    detail = client.get(f"/api/assistant/conversations/{conversation['id']}/").json()
    assert detail["title"] == "How can we reduce emissions?"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_chat_sends_company_data_and_history_to_model(viewer_user, emissions, settings):
    settings.GEMINI_API_KEY = "test-key"
    emissions[2] = Decimal("500")
    conversation = services.start_conversation(viewer_user)
    with patch("assistant.services.llm.complete", return_value="Use green power.") as complete:
        services.send_message(conversation, "First question")
        _, answer = services.send_message(conversation, "Follow-up")

    assert answer.content == "Use green power."
    instructions, messages = complete.call_args.args
    assert "Acme GmbH" in instructions and "Scope 2: 500.00" in instructions
    assert [m["content"] for m in messages] == ["First question", "Use green power.", "Follow-up"]


def test_chat_falls_back_when_ai_service_fails(viewer_user, emissions):
    conversation = services.start_conversation(viewer_user)
    with patch("assistant.services.llm.complete", side_effect=llm.LLMUnavailable("down")):
        _, answer = services.send_message(conversation, "Hello")
    assert "No emissions have been recorded" in answer.content


def test_llm_requires_api_key():
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("instructions", [{"role": "user", "content": "hi"}])


def test_conversations_are_private_to_their_user(api_for, viewer_user, make_member):
    colleague = make_member("carol")
    private = Conversation.objects.create(
        organisation=viewer_user.organisation, user=viewer_user, title="Mine"
    )
    client = api_for(colleague)
    assert client.get("/api/assistant/conversations/").json() == []
    assert client.get(f"/api/assistant/conversations/{private.pk}/").status_code == 404
    url = f"/api/assistant/conversations/{private.pk}/messages/"
    assert client.post(url, {"content": "hi"}).status_code == 404


def test_empty_message_is_rejected(api_for, viewer_user):
    client = api_for(viewer_user)
    conversation = client.post("/api/assistant/conversations/", {}).json()
    url = f"/api/assistant/conversations/{conversation['id']}/messages/"
    assert client.post(url, {"content": "   "}).status_code == 400


# Monthly summaries -------------------------------------------------------------------


def test_monthly_summary_compares_with_previous_month(organisation, emissions):
    emissions.update({1: Decimal("300"), 2: Decimal("100")})
    summary = services.generate_monthly_summary(organisation, date(2026, 9, 15))
    assert summary.month == date(2026, 9, 1)
    assert summary.totals["total"] == "400"
    assert summary.totals["change_percent"] == "0.0"
    assert "Scope 1" in summary.content

    services.generate_monthly_summary(organisation, date(2026, 9, 1))
    assert MonthlySummary.objects.count() == 1


def test_monthly_summary_uses_model_reply_when_configured(organisation, emissions, settings):
    settings.GEMINI_API_KEY = "test-key"
    emissions.update({1: Decimal("300"), 2: Decimal("100")})
    with patch(
        "assistant.services.llm.complete", return_value="Model wrote this summary."
    ) as complete:
        summary = services.generate_monthly_summary(organisation, date(2026, 9, 15))

    assert summary.content == "Model wrote this summary."
    instructions, messages = complete.call_args.args
    assert "Acme GmbH" in instructions
    assert messages[0]["role"] == "user"
    assert "2026-09" in messages[0]["content"]


def test_monthly_summary_falls_back_when_model_fails(organisation, emissions):
    emissions.update({1: Decimal("300"), 2: Decimal("100")})
    with patch("assistant.services.llm.complete", side_effect=llm.LLMUnavailable("down")):
        summary = services.generate_monthly_summary(organisation, date(2026, 9, 15))
    assert summary.content.startswith("### Acme GmbH: September 2026")
    assert "400.00 kg CO2e" in summary.content


def test_empty_month_does_not_call_the_model(organisation, emissions, settings):
    settings.GEMINI_API_KEY = "test-key"
    with patch("assistant.services.llm.complete") as complete:
        summary = services.generate_monthly_summary(organisation, date(2026, 9, 15))
    complete.assert_not_called()
    assert "No emissions were recorded for this month." in summary.content


def test_summary_api_permissions_and_validation(api_for, admin_user, viewer_user, emissions):
    assert (
        api_for(viewer_user).post("/api/assistant/summaries/", {"month": "2026-09"}).status_code
        == 403
    )
    client = api_for(admin_user)
    assert client.post("/api/assistant/summaries/", {"month": "2999-01"}).status_code == 400
    created = client.post("/api/assistant/summaries/", {"month": "2026-09"})
    assert created.status_code == 201
    assert created.json()["generated_by"] == "alice"
    assert len(api_for(viewer_user).get("/api/assistant/summaries/").json()) == 1


def test_summaries_are_scoped_to_organisation(api_for, organisation, emissions):
    other = Organisation.objects.create(name="Rival AG")
    services.generate_monthly_summary(other, date(2026, 9, 1))
    member = User.objects.create_user(username="m", password="x", organisation=organisation)
    assert api_for(member).get("/api/assistant/summaries/").json() == []
