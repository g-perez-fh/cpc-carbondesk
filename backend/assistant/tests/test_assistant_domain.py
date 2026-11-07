"""Plain-Python tests for the Hometask 1 assistant classes. No Django, no database, no AI."""

from datetime import date
from decimal import Decimal

import pytest

from accounts.domain import Organisation, ReductionTarget
from assistant.domain import (
    AssistantService,
    ChatSession,
    MonthlySummaryBuilder,
    RecommendationEngine,
    scope_totals,
)
from shared.models import ActivityRecord


def record(kg, scope=1, day=date(2026, 10, 15), organisation_id=1):
    return ActivityRecord(
        organisation_id=organisation_id,
        site="Plant",
        date=day,
        scope=scope,
        category="Electricity" if scope == 2 else "Diesel",
        quantity=Decimal("1"),
        unit="kWh",
        factor_value=Decimal(str(kg)),
        kg_co2e=Decimal(str(kg)),
    )


def test_scope_totals_sum_kg_co2e_and_require_activity_records():
    assert scope_totals([record(10), record(5, scope=2), record(1)]) == {
        1: Decimal("11"),
        2: Decimal("5"),
        3: Decimal("0"),
    }
    with pytest.raises(TypeError):
        scope_totals([{"scope": 1, "kg_co2e": 10}])


# RecommendationEngine -----------------------------------------------------------------


def test_engine_validates_limit_and_catalogue():
    for limit in (0, 21, 2.5, True):
        with pytest.raises(ValueError):
            RecommendationEngine(limit=limit)
    with pytest.raises(TypeError):
        RecommendationEngine().setup("not a list")
    bad = {"title": "x", "scope": 1, "share": "1.5", "effort": "low"}
    with pytest.raises(ValueError):
        RecommendationEngine().setup([bad])


def test_engine_ranks_measures_by_savings():
    engine = RecommendationEngine(limit=2).setup()
    recommendations = engine.recommend([record(1000, scope=1), record(2000, scope=2)])
    assert [r["title"] for r in recommendations] == [
        "Switch to renewable electricity",
        "Electrify company vehicles",
    ]
    assert recommendations[0]["savings_kg_co2e"] == Decimal("1400.00")


def test_engine_without_records_recommends_nothing():
    assert RecommendationEngine().setup().recommend([]) == []


# ChatSession ----------------------------------------------------------------------------


def test_session_validates_attributes():
    with pytest.raises(ValueError):
        ChatSession(user_id=0)
    with pytest.raises(ValueError):
        ChatSession(user_id=1, title="x" * 121)
    with pytest.raises(ValueError):
        ChatSession(user_id=1, history_limit=0)


@pytest.mark.parametrize("role, content", [("system", "hi"), ("user", "   "), ("user", "x" * 2001)])
def test_session_rejects_invalid_messages(role, content):
    with pytest.raises(ValueError):
        ChatSession(user_id=1).add_message(role, content)


def test_first_question_becomes_title_and_history_is_bounded():
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"} for i in range(6)
    ]
    session = ChatSession(user_id=1, history_limit=4).setup(messages)
    assert session.title == "message 0"
    assert [m["content"] for m in session.recent_history()] == [f"message {i}" for i in range(2, 6)]


# MonthlySummaryBuilder -----------------------------------------------------------------


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "October", ""])
def test_summary_validates_month(month):
    with pytest.raises(ValueError):
        MonthlySummaryBuilder("Acme", month)


def test_summary_compares_month_with_previous_month():
    records = [
        record(300, day=date(2026, 10, 3)),
        record(100, scope=2, day=date(2026, 10, 20)),
        record(500, day=date(2026, 9, 9)),
        record(9999, day=date(2025, 10, 1)),
    ]
    builder = MonthlySummaryBuilder("Acme", "2026-10").setup(records)
    assert builder.total_kg_co2e() == Decimal("400")
    assert builder.change_percent() == Decimal("-20.0")
    assert builder.largest_scope() == 1
    assert "down 20.0%" in builder.build()


def test_summary_january_compares_with_previous_december():
    records = [record(50, day=date(2026, 1, 5)), record(100, day=date(2025, 12, 5))]
    assert MonthlySummaryBuilder("Acme", "2026-01").setup(records).change_percent() == Decimal(
        "-50.0"
    )


def test_summary_without_data():
    builder = MonthlySummaryBuilder("Acme", "2026-10").setup([])
    assert builder.largest_scope() is None and builder.change_percent() is None
    assert "No emissions were recorded" in builder.build()


# AssistantService ------------------------------------------------------------------------


def make_service():
    return AssistantService(Organisation(1, "Acme GmbH"))


def test_service_requires_accounts_types():
    with pytest.raises(TypeError):
        AssistantService("Acme")
    with pytest.raises(TypeError):
        make_service().setup([], targets=["not a target"])
    with pytest.raises(TypeError):
        AssistantService(Organisation(1, "Acme"), engine=object())


def test_service_answers_from_own_records_and_targets_only():
    target = ReductionTarget(1, 2025, 1000, 2030, 40, scope="all")
    other_target = ReductionTarget(2, 2025, 1, 2030, 40)
    service = make_service().setup(
        [record(600, scope=2), record(100), record(99999, organisation_id=2)],
        targets=[target, other_target],
    )
    answer = service.answer("How are we doing?", year=2026)
    assert "Scope 2: 600.00 kg CO2e" in answer
    assert "99,999" not in answer
    assert "Target scope all, 2030: on track" in answer
    assert "Switch to renewable electricity" in answer
    assert target.actual_kg_co2e(2026) == Decimal("700")


def test_service_answer_validation_and_empty_data():
    service = make_service().setup([])
    with pytest.raises(ValueError):
        service.answer("  ")
    assert "No emissions have been recorded" in service.answer("Hi")


def test_service_monthly_summary_uses_the_builder():
    service = make_service().setup([record(250)])
    assert "Acme GmbH: 2026-10" in service.monthly_summary("2026-10")
