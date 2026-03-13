"""Tests for application.event_bus — subscribe, emit, thread safety."""

from __future__ import annotations

import threading
from typing import Any

from meeting_copilot.application.event_bus import EventBus
from meeting_copilot.domain.events import (
    AudioChunkReady,
    ErrorOccurred,
    ListeningStateChanged,
    TranscriptSegmentAdded,
)


class TestEventBusSubscribeEmit:
    """Basic subscribe/emit behavior."""

    def setup_method(self) -> None:
        self.bus = EventBus()

    def test_subscribe_and_emit_calls_callback(self) -> None:
        received: list[ListeningStateChanged] = []
        self.bus.subscribe(ListeningStateChanged, received.append)
        event = ListeningStateChanged(is_listening=True)
        self.bus.emit(event)
        assert received == [event]

    def test_emit_without_subscribers_does_not_error(self) -> None:
        self.bus.emit(ListeningStateChanged(is_listening=False))
        # No assertion needed — just shouldn't raise

    def test_multiple_subscribers_all_called(self) -> None:
        calls_a: list[Any] = []
        calls_b: list[Any] = []
        self.bus.subscribe(ListeningStateChanged, calls_a.append)
        self.bus.subscribe(ListeningStateChanged, calls_b.append)

        event = ListeningStateChanged(is_listening=True)
        self.bus.emit(event)

        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_different_event_types_are_isolated(self) -> None:
        listening_events: list[Any] = []
        error_events: list[Any] = []

        self.bus.subscribe(ListeningStateChanged, listening_events.append)
        self.bus.subscribe(ErrorOccurred, error_events.append)

        self.bus.emit(ListeningStateChanged(is_listening=True))
        self.bus.emit(
            ErrorOccurred(source="test", message="oops", recoverable=True)
        )

        assert len(listening_events) == 1
        assert len(error_events) == 1

    def test_handler_exception_does_not_break_other_handlers(self) -> None:
        results: list[Any] = []

        def bad_handler(event: Any) -> None:
            raise RuntimeError("boom")

        self.bus.subscribe(ListeningStateChanged, bad_handler)
        self.bus.subscribe(ListeningStateChanged, results.append)

        self.bus.emit(ListeningStateChanged(is_listening=True))
        # Second handler should still have been called
        assert len(results) == 1

    def test_clear_removes_all_subscriptions(self) -> None:
        results: list[Any] = []
        self.bus.subscribe(ListeningStateChanged, results.append)
        self.bus.clear()
        self.bus.emit(ListeningStateChanged(is_listening=True))
        assert results == []


class TestEventBusThreadSafety:
    """Concurrent subscribe/emit must not corrupt internal state."""

    def test_concurrent_emit_and_subscribe(self) -> None:
        bus = EventBus()
        results: list[AudioChunkReady] = []
        lock = threading.Lock()
        errors: list[Exception] = []

        def subscriber(event: AudioChunkReady) -> None:
            with lock:
                results.append(event)

        def emit_loop() -> None:
            try:
                for _ in range(100):
                    bus.emit(AudioChunkReady(audio=b"test", length_ms=100))
            except Exception as e:
                errors.append(e)

        def subscribe_loop() -> None:
            try:
                for _ in range(100):
                    bus.subscribe(AudioChunkReady, subscriber)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=emit_loop)
        t2 = threading.Thread(target=subscribe_loop)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Thread errors: {errors}"
