"""Tests for the shared framework: ABC, iterator protocol, and | / __ror__ chaining."""

from datetime import datetime
from decimal import Decimal

import pytest

from stream_processing.base import ActivityEvent, EventSource, Pipeline, StreamProcessor


def make_event(event_id="e1", scope=1, category="Diesel", quantity="10"):
    return ActivityEvent(
        event_id=event_id,
        source="freight",
        scope=scope,
        category=category,
        quantity=Decimal(quantity),
        unit="l",
        timestamp=datetime(2026, 1, 1),
    )


class PassThrough(StreamProcessor):
    """A trivial processor used only by these tests, to prove polymorphism independent
    of any real subsystem processor."""

    def __init__(self, tag):
        self.tag = tag

    def process(self, events):
        for event in events:
            event.metadata["seen_by"] = event.metadata.get("seen_by", []) + [self.tag]
            yield event


def test_stream_processor_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        StreamProcessor()


def test_event_source_implements_iterator_protocol():
    source = EventSource([make_event("a"), make_event("b")])
    assert iter(source) is source
    assert next(source).event_id == "a"
    assert next(source).event_id == "b"


def test_event_source_exhausts_with_stop_iteration():
    source = EventSource([make_event("a")])
    next(source)
    with pytest.raises(StopIteration):
        next(source)


def test_pipe_operator_chains_two_processors():
    pipeline = PassThrough("first") | PassThrough("second")
    assert isinstance(pipeline, Pipeline)
    results = list(pipeline.process([make_event("a")]))
    assert results[0].metadata["seen_by"] == ["first", "second"]


def test_pipe_operator_from_plain_list_via_ror():
    pipeline = [make_event("a"), make_event("b")] | PassThrough("tagged")
    assert isinstance(pipeline, Pipeline)
    results = list(pipeline.process(()))
    assert [e.event_id for e in results] == ["a", "b"]
    assert all(e.metadata["seen_by"] == ["tagged"] for e in results)


def test_pipe_operator_from_event_source():
    source = EventSource([make_event("a")])
    pipeline = source | PassThrough("x") | PassThrough("y")
    results = list(pipeline)
    assert results[0].metadata["seen_by"] == ["x", "y"]


def test_pipeline_is_itself_a_stream_processor_polymorphism():
    inner = PassThrough("a") | PassThrough("b")
    outer = inner | PassThrough("c")
    results = list(outer.process([make_event("a")]))
    assert results[0].metadata["seen_by"] == ["a", "b", "c"]
