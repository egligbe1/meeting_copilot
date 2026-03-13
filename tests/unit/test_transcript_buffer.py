"""Tests for application.transcript_buffer — RollingTranscriptBuffer."""

from __future__ import annotations

from datetime import datetime

from meeting_copilot.application.transcript_buffer import RollingTranscriptBuffer
from meeting_copilot.domain.events import TranscriptSegmentAdded
from meeting_copilot.domain.settings import Settings


class TestRollingTranscriptBuffer:
    """RollingTranscriptBuffer word counting and trigger logic."""

    def _make_event(self, text: str, speaker: str = "You") -> TranscriptSegmentAdded:
        return TranscriptSegmentAdded(
            timestamp=datetime(2026, 3, 13, 14, 30, 0),
            speaker=speaker,
            text=text,
        )

    def test_initially_should_not_trigger(self) -> None:
        buf = RollingTranscriptBuffer(Settings())
        assert not buf.should_trigger()

    def test_trigger_after_enough_words(self) -> None:
        buf = RollingTranscriptBuffer(Settings(word_trigger=5))
        buf.add(self._make_event("one two three four five"))
        assert buf.should_trigger()

    def test_no_trigger_below_threshold(self) -> None:
        buf = RollingTranscriptBuffer(Settings(word_trigger=10))
        buf.add(self._make_event("one two three"))
        assert not buf.should_trigger()

    def test_reset_trigger_count(self) -> None:
        buf = RollingTranscriptBuffer(Settings(word_trigger=3))
        buf.add(self._make_event("one two three"))
        assert buf.should_trigger()
        buf.reset_trigger_count()
        assert not buf.should_trigger()

    def test_get_context_string_format(self) -> None:
        buf = RollingTranscriptBuffer(Settings())
        buf.add(self._make_event("hello world", speaker="Meeting"))
        ctx = buf.get_context_string()
        assert "[14:30] Meeting: hello world" in ctx

    def test_total_word_count(self) -> None:
        buf = RollingTranscriptBuffer(Settings())
        buf.add(self._make_event("one two"))
        buf.add(self._make_event("three four five"))
        assert buf.total_word_count == 5
