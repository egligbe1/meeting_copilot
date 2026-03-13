"""SessionLogger — writes transcript + questions to timestamped session folders.

Session folder: ``~/.meeting-copilot/sessions/YYYY-MM-DD_HH-MM/``
Files:
    * ``transcript.txt``  — appended in real time
    * ``questions.txt``   — appended when QuestionsReady fires
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from meeting_copilot.domain.events import QuestionsReady, TranscriptSegmentAdded

logger = logging.getLogger(__name__)


def _sessions_dir() -> Path:
    """Return the sessions root directory, creating it if needed."""
    sessions = Path.home() / ".meeting-copilot" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions


class SessionLogger:
    """Write transcript and question data to a timestamped session folder."""

    def __init__(self) -> None:
        self._session_dir: Path | None = None
        self._transcript_path: Path | None = None
        self._questions_path: Path | None = None

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
        self._questions_path = self._session_dir / "questions.txt"

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

    def on_questions(self, event: QuestionsReady) -> None:
        """Append generated questions to ``questions.txt``."""
        if self._questions_path is None:
            return

        time_str = datetime.now().strftime("%H:%M:%S")
        lines = [f"[{time_str}] — context: {event.context_word_count} words\n"]
        for i, question in enumerate(event.questions, start=1):
            lines.append(f"  {i}. {question}\n")
        lines.append("\n")

        try:
            with self._questions_path.open("a", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError:
            logger.exception("Failed to write questions")

    # ------------------------------------------------------------------
    # Data Retrieval & Summary
    # ------------------------------------------------------------------

    def get_full_transcript(self) -> str:
        """Read and return the entire transcript file content."""
        if self._transcript_path is None or not self._transcript_path.exists():
            return ""

        try:
            return self._transcript_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read full transcript")
            return ""

    def save_summary(self, summary_md: str) -> Path | None:
        """Write the final AI summary to ``summary.md`` in the session dir."""
        if self._session_dir is None:
            return None

        summary_path = self._session_dir / "summary.md"
        try:
            summary_path.write_text(summary_md, encoding="utf-8")
            logger.info("Summary saved to %s", summary_path)
            return summary_path
        except OSError:
            logger.exception("Failed to save summary")
            return None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def sessions_root() -> Path:
        """Return the root sessions directory path."""
        return _sessions_dir()
