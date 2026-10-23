"""Tests for clearing interview context and ignoring stale work."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meeting_copilot.application.orchestrator import Orchestrator
from meeting_copilot.domain.events import (
    AnswerReady,
    ClearContextRequested,
    ContextCleared,
    TranscriptSegmentAdded,
)


def test_clear_context_resets_buffer_and_advances_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = Mock()
    monkeypatch.setattr(
        "meeting_copilot.application.orchestrator.get_bus", lambda: bus
    )
    orchestrator = SimpleNamespace(
        _context_generation=2,
        buffer=Mock(),
        capture=Mock(),
    )

    Orchestrator._on_clear_context(orchestrator, ClearContextRequested())

    orchestrator.buffer.clear.assert_called_once_with()
    orchestrator.capture.clear_context.assert_called_once_with(3)
    assert orchestrator._context_generation == 3
    bus.emit.assert_called_once_with(ContextCleared(generation=3))


def test_stale_transcript_is_not_added_to_buffer() -> None:
    buffer = Mock()
    orchestrator = SimpleNamespace(
        _context_generation=3,
        buffer=buffer,
    )
    event = TranscriptSegmentAdded(
        timestamp=datetime(2026, 10, 15, 10, 0),
        speaker="Meeting",
        text="Old question",
        context_generation=2,
    )

    Orchestrator._on_segment(orchestrator, event)

    buffer.add.assert_not_called()


def test_stale_answer_is_not_logged_or_printed() -> None:
    session_logger = Mock()
    print_answer = Mock()
    orchestrator = SimpleNamespace(
        _context_generation=3,
        logger=session_logger,
        _on_answer=print_answer,
    )
    event = AnswerReady(
        answer="Old answer",
        talking_points=(),
        follow_up=None,
        context_word_count=10,
        context_generation=2,
    )

    Orchestrator._on_answer_event(orchestrator, event)

    session_logger.on_answer.assert_not_called()
    print_answer.assert_not_called()
