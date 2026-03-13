"""Tests for infrastructure.persistence.session — SessionLogger."""

from __future__ import annotations

from datetime import datetime

from meeting_copilot.domain.events import QuestionsReady, TranscriptSegmentAdded
from meeting_copilot.infrastructure.persistence.session import SessionLogger


class TestSessionLogger:
    """SessionLogger creates folders and writes transcript/questions."""

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

    def test_on_questions_writes_questions(self, tmp_path: object) -> None:
        from pathlib import Path

        tmp = Path(str(tmp_path))
        logger = SessionLogger()

        import unittest.mock as mock

        with mock.patch(
            "meeting_copilot.infrastructure.persistence.session._sessions_dir",
            return_value=tmp,
        ):
            logger.begin_session()

        event = QuestionsReady(
            questions=(
                "What is the baseline?",
                "Who owns the follow-up?",
            ),
            context_word_count=83,
        )
        logger.on_questions(event)

        questions = (logger.session_dir / "questions.txt").read_text(  # type: ignore[union-attr]
            encoding="utf-8"
        )
        assert "context: 83 words" in questions
        assert "1. What is the baseline?" in questions
        assert "2. Who owns the follow-up?" in questions

    def test_on_segment_before_begin_does_nothing(self) -> None:
        logger = SessionLogger()
        # Should not raise
        event = TranscriptSegmentAdded(
            timestamp=datetime.now(),
            speaker="Meeting",
            text="hello",
        )
        logger.on_segment(event)
