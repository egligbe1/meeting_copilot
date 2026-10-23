"""Tests for infrastructure.persistence.session — SessionLogger."""

from __future__ import annotations

from datetime import datetime

from meeting_copilot.domain.events import AnswerReady, TranscriptSegmentAdded
from meeting_copilot.infrastructure.persistence.session import SessionLogger


class TestSessionLogger:
    """SessionLogger creates folders and writes transcript/answer guidance."""

    def test_begin_session_creates_directory(self, tmp_path: object) -> None:
        logger = SessionLogger()
        import unittest.mock as mock

        with mock.patch(
            "meeting_copilot.infrastructure.persistence.session._sessions_dir",
            return_value=tmp_path,  # type: ignore[arg-type]
        ):
            session_dir = logger.begin_session()

        assert session_dir.exists()
        assert session_dir.is_dir()

    def test_on_segment_writes_transcript(self, tmp_path: object) -> None:
        from pathlib import Path

        tmp = Path(str(tmp_path))
        logger = SessionLogger()

        import unittest.mock as mock

        with mock.patch(
            "meeting_copilot.infrastructure.persistence.session._sessions_dir",
            return_value=tmp,
        ):
            logger.begin_session()

        event = TranscriptSegmentAdded(
            timestamp=datetime(2026, 3, 13, 14, 30, 5),
            speaker="You",
            text="the Q3 numbers look strong",
        )
        logger.on_segment(event)

        transcript = (logger.session_dir / "transcript.txt").read_text(  # type: ignore[union-attr]
            encoding="utf-8"
        )
        assert "[14:30:05] You: the Q3 numbers look strong" in transcript

    def test_on_answer_writes_guidance(self, tmp_path: object) -> None:
        from pathlib import Path

        tmp = Path(str(tmp_path))
        logger = SessionLogger()

        import unittest.mock as mock

        with mock.patch(
            "meeting_copilot.infrastructure.persistence.session._sessions_dir",
            return_value=tmp,
        ):
            logger.begin_session()

        event = AnswerReady(
            answer="I would begin by defining the data contract.",
            talking_points=("Version schemas", "Monitor freshness"),
            follow_up="Which latency target matters most?",
            context_word_count=83,
        )
        logger.on_answer(event)

        guidance = (logger.session_dir / "answer_guidance.txt").read_text(  # type: ignore[union-attr]
            encoding="utf-8"
        )
        assert "context: 83 words" in guidance
        assert "I would begin by defining the data contract." in guidance
        assert "• Version schemas" in guidance

    def test_on_segment_before_begin_does_nothing(self) -> None:
        logger = SessionLogger()
        # Should not raise
        event = TranscriptSegmentAdded(
            timestamp=datetime.now(),
            speaker="Meeting",
            text="hello",
        )
        logger.on_segment(event)
