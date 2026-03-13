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

    def test_pruning_logic(self):
        # Set context limit to 300 words (2 minutes * 150)
        settings = Settings(context_window_minutes=2)
        buffer = RollingTranscriptBuffer(settings)

        # Add a large segment
        text = "word " * 200
        buffer.add(TranscriptSegmentAdded(datetime.now(), "Alice", text))

        # Add another large segment
        buffer.add(TranscriptSegmentAdded(datetime.now(), "Bob", text))

        # Word count should be pruned to ~300
        # Since each is 200, two is 400. Pruning should happen (prunes oldest, Bob remains).
        assert buffer.total_word_count <= 400
        
        # Add another - should definitely prune Bob if Charlie is added and Bob was oldest?
        # Actually pruning loop: while total > context_limit and len > 1: popleft
        # Alice was first. Adding Bob (200) + Alice (200) = 400. Limit is 300.
        # Pruning removes Alice. Total = 200 (Bob).
        # Adding Charlie (200). Total = 400. Limit is 300.
        # Pruning removes Bob. Total = 200 (Charlie).
        buffer.add(TranscriptSegmentAdded(datetime.now(), "Charlie", text))
        ctx = buffer.get_context_string()
        assert "Alice" not in ctx
        assert "Bob" not in ctx
        assert "Charlie" in ctx


    def test_trigger_logic(self):
        settings = Settings(word_trigger=50)
        buffer = RollingTranscriptBuffer(settings)

        buffer.add(TranscriptSegmentAdded(datetime.now(), "You", "Hello world"))
        assert not buffer.should_trigger()

        buffer.add(TranscriptSegmentAdded(datetime.now(), "Speaker", "This is a much longer sentence " * 10 + "that should definitely trigger the word threshold."))
        assert buffer.should_trigger()


    def test_reset_trigger(self):
        settings = Settings()
        buffer = RollingTranscriptBuffer(settings)
        # Manually poking private state for test
        buffer._new_word_count = 100
        buffer.reset_trigger_count()
        assert buffer._new_word_count == 0


    def test_context_formatting(self):
        settings = Settings()
        buffer = RollingTranscriptBuffer(settings)
        ts = datetime(2024, 1, 1, 12, 0)
        buffer.add(TranscriptSegmentAdded(ts, "Alice", "Hi"))

        ctx = buffer.get_context_string()
        assert "[12:00] Alice: Hi" in ctx

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
