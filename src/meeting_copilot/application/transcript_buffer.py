"""RollingTranscriptBuffer — thread-safe deque with word-count trigger.

Accumulates TranscriptSegment objects and fires the LLM when enough new
words have been captured.
"""

from __future__ import annotations

import threading
from collections import deque

from meeting_copilot.domain.events import TranscriptSegmentAdded
from meeting_copilot.domain.models import TranscriptSegment
from meeting_copilot.domain.settings import Settings


class RollingTranscriptBuffer:
    """Rolling window of transcript segments with LLM trigger logic.
    
    Maintains a strict word-count window by pruning old segments.
    """

    def __init__(self, settings: Settings) -> None:
        self._buffer: deque[TranscriptSegment] = deque()
        self._new_word_count = 0
        self._word_trigger = settings.word_trigger
        # approx 100 words per minute for context calculation
        self._context_limit = settings.context_window_minutes * 150
        self._lock = threading.Lock()

    def add(self, event: TranscriptSegmentAdded) -> None:
        """Add a transcript segment and prune buffer to stay within context limit."""
        segment = TranscriptSegment(
            timestamp=event.timestamp,
            speaker=event.speaker,
            text=event.text,
        )
        with self._lock:
            self._buffer.append(segment)
            self._new_word_count += segment.word_count
            self._prune()

    def _prune(self) -> None:
        """Prune oldest segments if total word count exceeds limit."""
        total = sum(seg.word_count for seg in self._buffer)
        while total > self._context_limit and len(self._buffer) > 1:
            removed = self._buffer.popleft()
            total -= removed.word_count

    def should_trigger(self) -> bool:
        """Return True if enough new words have accumulated for an LLM call."""
        with self._lock:
            return self._new_word_count >= self._word_trigger

    def get_context_string(self) -> str:
        """Format the buffer as ``'[HH:MM] Speaker: text\\n'``."""
        with self._lock:
            lines = []
            for seg in self._buffer:
                time_str = seg.timestamp.strftime("%H:%M")
                lines.append(f"[{time_str}] {seg.speaker}: {seg.text}")
            return "\n".join(lines)

    def reset_trigger_count(self) -> None:
        """Reset the new-word counter."""
        with self._lock:
            self._new_word_count = 0

    @property
    def total_word_count(self) -> int:
        """Total words currently in the buffer."""
        with self._lock:
            return sum(seg.word_count for seg in self._buffer)
