"""Tests for event system."""

import pytest
from mocharpa.events import (
    Event,
    EventBus,
    PipelineStartEvent,
    PipelineEndEvent,
    StepStartEvent,
    StepEndEvent,
    StepSkippedEvent,
    StepErrorEvent,
    DriverConnectEvent,
    DriverDisconnectEvent,
    ElementFoundEvent,
    ElementNotFoundEvent,
    PipelineEvent,
)


class TestEventBase:
    def test_timestamp_set(self):
        e = Event()
        assert e.timestamp > 0

    def test_stop_propagation(self):
        e = Event()
        assert not e.is_stopped
        e.stop_propagation()
        assert e.is_stopped

    def test_prevent_default(self):
        e = Event()
        assert not e.is_default_prevented
        e.prevent_default()
        assert e.is_default_prevented


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(PipelineStartEvent, lambda e: received.append(e.pipeline_name))
        bus.emit(PipelineStartEvent(pipeline_name="test"))
        assert received == ["test"]

    def test_stop_propagation(self):
        bus = EventBus()
        called = []

        def first(e):
            called.append("first")
            e.stop_propagation()

        def second(e):
            called.append("second")

        bus.subscribe(StepStartEvent, first)
        bus.subscribe(StepStartEvent, second)
        bus.emit(StepStartEvent(step_name="test"))
        assert called == ["first"]

    def test_once(self):
        bus = EventBus()
        count = [0]
        bus.once(StepEndEvent, lambda e: count.__setitem__(0, count[0] + 1))
        bus.subscribe(StepEndEvent, lambda e: count.__setitem__(0, count[0] + 1))
        bus.emit(StepEndEvent(step_name="a"))
        bus.emit(StepEndEvent(step_name="b"))
        # once fires once (1) + regular fires twice (2) = 3
        assert count[0] == 3

    def test_mro_dispatch(self):
        bus = EventBus()
        names = []
        bus.subscribe(PipelineEvent, lambda e: names.append(type(e).__name__))
        bus.emit(PipelineStartEvent(pipeline_name="x"))
        bus.emit(PipelineEndEvent(pipeline_name="x"))
        assert names == ["PipelineStartEvent", "PipelineEndEvent"]

    def test_priority_ordering(self):
        bus = EventBus()
        order = []
        bus.subscribe(PipelineStartEvent, lambda e: order.append("low"), priority=0)
        bus.subscribe(PipelineStartEvent, lambda e: order.append("high"), priority=10)
        bus.emit(PipelineStartEvent(pipeline_name="x"))
        assert order == ["high", "low"]

    def test_subscriber_count(self):
        bus = EventBus()
        bus.subscribe(PipelineStartEvent, lambda e: None)
        bus.subscribe(PipelineStartEvent, lambda e: None)
        bus.subscribe(StepEndEvent, lambda e: None)
        assert bus.subscriber_count(PipelineStartEvent) == 2
        assert bus.subscriber_count() == 3
        bus.clear()
        assert bus.subscriber_count() == 0


class TestConcreteEvents:
    def test_pipeline_start(self):
        e = PipelineStartEvent(pipeline_name="test", data={"x": 1})
        assert e.pipeline_name == "test"
        assert e.data == {"x": 1}
        assert not e.is_stopped

    def test_pipeline_end(self):
        e = PipelineEndEvent(pipeline_name="test", success=True, elapsed=1.5, step_count=3, error_count=1)
        assert e.success is True
        assert e.elapsed == 1.5
        assert e.step_count == 3
        assert e.error_count == 1

    def test_step_error(self):
        e = StepErrorEvent(step_name="bad", error="boom", unhandled=True)
        assert e.step_name == "bad"
        assert e.error == "boom"
        assert e.unhandled is True

    def test_driver_connect(self):
        e = DriverConnectEvent(driver_name="MockDriver")
        assert e.driver_name == "MockDriver"

    def test_element_found(self):
        e = ElementFoundEvent(locator="name:X", element="el", timeout=5.0)
        assert e.locator == "name:X"
        assert e.timeout == 5.0
