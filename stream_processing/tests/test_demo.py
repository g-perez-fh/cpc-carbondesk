"""Smoke tests for the demo script: sample data generation and a full run."""

from stream_processing.base import ActivityEvent
from stream_processing.demo import generate_sample_events, run_demo


def test_generate_sample_events_yields_activity_events():
    events = list(generate_sample_events(count=6))
    assert len(events) == 6
    assert all(isinstance(event, ActivityEvent) for event in events)
    assert {event.scope for event in events} == {1, 2, 3}


def test_generate_sample_events_is_deterministic_for_a_given_seed():
    first = [e.quantity for e in generate_sample_events(count=5, seed=1)]
    second = [e.quantity for e in generate_sample_events(count=5, seed=1)]
    assert first == second


def test_run_demo_executes_without_error(capsys):
    run_demo()
    output = capsys.readouterr().out
    assert "Final totals by scope" in output
    assert "Peak events" in output
    assert "Target alerts" in output
    assert "Assistant recommendations" in output
