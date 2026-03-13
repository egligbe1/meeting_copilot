import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from pathlib import Path

from meeting_copilot.infrastructure.persistence.session import SessionLogger
from meeting_copilot.application.orchestrator import Orchestrator, AdvisorWorker
from meeting_copilot.domain.settings import Settings
from meeting_copilot.domain.events import SessionSummaryReady, TranscriptSegmentAdded

class TestSummaryLogic:
    def test_session_logger_summary_io(self, tmp_path):
        # Mocking _sessions_dir to use tmp_path
        with patch("meeting_copilot.infrastructure.persistence.session._sessions_dir", return_value=tmp_path):
            logger = SessionLogger()
            logger.begin_session()
            
            # Add some transcript content
            logger.on_segment(TranscriptSegmentAdded(datetime.now(), "Alice", "We should build a rocket."))
            logger.on_segment(TranscriptSegmentAdded(datetime.now(), "Bob", "Agreed, let's start Monday."))
            
            # Verify transcript retrieval
            full_text = logger.get_full_transcript()
            assert "Alice: We should build a rocket." in full_text
            assert "Bob: Agreed, let's start Monday." in full_text
            
            # Verify summary saving
            summary_content = "# Meeting Summary\n\n1. Build rocket."
            summary_path = logger.save_summary(summary_content)
            assert summary_path.exists()
            assert summary_path.read_text() == summary_content

    @patch("meeting_copilot.application.orchestrator.GroqSTTClient")
    @patch("meeting_copilot.application.orchestrator.GroqLLMClient")
    @patch("meeting_copilot.application.orchestrator.AudioCaptureManager")
    def test_orchestrator_stop_triggers_summary(self, mock_audio, mock_llm, mock_stt):
        settings = Settings()
        orchestrator = Orchestrator(settings, "fake-key")
        
        # Mock logger to return transcript
        orchestrator.logger.get_full_transcript = MagicMock(return_value="Some transcript")
        
        # Track worker creation
        with patch.object(orchestrator, "_track_worker") as mock_track:
            orchestrator.stop()
            
            # Verify that a worker was started with task='summary'
            assert mock_track.called
            worker = mock_track.call_args[0][0]
            assert isinstance(worker, AdvisorWorker)
            assert worker._task == "summary"
            assert worker._context == "Some transcript"

    def test_orchestrator_on_summary_ready(self):
        settings = Settings()
        orchestrator = Orchestrator(settings, "fake-key")
        orchestrator.logger.save_summary = MagicMock(return_value=Path("summary.md"))
        
        event = SessionSummaryReady(summary_md="The final summary")
        orchestrator._on_summary_ready(event)
        
        orchestrator.logger.save_summary.assert_called_with("The final summary")
