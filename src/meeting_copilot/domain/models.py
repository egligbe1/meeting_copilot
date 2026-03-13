"""Domain value objects — TranscriptSegment and QuestionCard.

These are simple data containers used across the application.
They have no dependencies on infrastructure or UI layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TranscriptSegment:
    """A single segment of transcribed speech."""

    timestamp: datetime
    speaker: str  # 'You' | 'Meeting'
    text: str

    @property
    def word_count(self) -> int:
        """Return the number of words in this segment."""
        return len(self.text.split())

    def format_line(self) -> str:
        """Format as '[HH:MM:SS] Speaker: text'."""
        time_str = self.timestamp.strftime("%H:%M:%S")
        return f"[{time_str}] {self.speaker}: {self.text}"


@dataclass(frozen=True)
class QuestionCard:
    """A suggested question to display in the overlay."""

    question: str
    generated_at: datetime = field(default_factory=datetime.now)
    dismissed: bool = field(default=False)
