"""SessionLogger — writes transcript + answer guidance to session folders.

Session folder: ``~/.meeting-copilot/sessions/YYYY-MM-DD_HH-MM/``
Files:
    * ``transcript.txt``  — appended in real time
    * ``answer_guidance.txt`` — appended when AnswerReady fires
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from meeting_copilot.domain.events import AnswerReady, TranscriptSegmentAdded

logger = logging.getLogger(__name__)


def _sessions_dir() -> Path:
    """Return the sessions root directory, creating it if needed."""
    sessions = Path.home() / ".interview-copilot" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions


class SessionLogger:
    """Write transcript and question data to a timestamped session folder."""

    def __init__(self) -> None:
        self._session_dir: Path | None = None
        self._transcript_path: Path | None = None
        self._answers_path: Path | None = None

    @property
    def session_dir(self) -> Path | None:
        """Return the current session directory, or None if not started."""
        return self._session_dir

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def begin_session(self) -> Path:
        """Create a new session folder and return its path."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        self._session_dir = _sessions_dir() / timestamp
        self._session_dir.mkdir(parents=True, exist_ok=True)

        self._transcript_path = self._session_dir / "transcript.txt"
        self._answers_path = self._session_dir / "answer_guidance.txt"

        logger.info("Session started: %s", self._session_dir)
        return self._session_dir

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_segment(self, event: TranscriptSegmentAdded) -> None:
        """Append a transcript segment to ``transcript.txt``."""
        if self._transcript_path is None:
            return

        time_str = event.timestamp.strftime("%H:%M:%S")
        line = f"[{time_str}] {event.speaker}: {event.text}\n"

        try:
            with self._transcript_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            logger.exception("Failed to write transcript segment")

    def on_answer(self, event: AnswerReady) -> None:
        """Append generated answer guidance to ``answer_guidance.txt``."""
        if self._answers_path is None:
            return

        time_str = datetime.now().strftime("%H:%M:%S")
        lines = [f"[{time_str}] — context: {event.context_word_count} words\n"]
        lines.append(f"Answer: {event.answer}\n")
        for point in event.talking_points:
            lines.append(f"  • {point}\n")
        if event.follow_up:
            lines.append(f"Clarify: {event.follow_up}\n")
        lines.append("\n")

        try:
            with self._answers_path.open("a", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError:
            logger.exception("Failed to write answer guidance")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def sessions_root() -> Path:
        """Return the root sessions directory path."""
        return _sessions_dir()
