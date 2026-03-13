"""Orchestrator — wires all layers together via EventBus subscriptions.

The Orchestrator is the only module that knows about all layers. It is
instantiated once in ``__main__.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QThread, Slot

from meeting_copilot.application.event_bus import get_bus, subscribe_qt
from meeting_copilot.application.transcript_buffer import RollingTranscriptBuffer
from meeting_copilot.domain.events import (
    AudioChunkReady,
    ErrorOccurred,
    ListeningStateChanged,
    QuestionsReady,
    TranscriptSegmentAdded,
)
from meeting_copilot.domain.settings import Settings
from meeting_copilot.infrastructure.audio.capture import AudioCaptureManager
from meeting_copilot.infrastructure.groq.llm import GroqLLMClient
from meeting_copilot.infrastructure.groq.stt import GroqSTTClient
from meeting_copilot.infrastructure.persistence.session import SessionLogger

logger = logging.getLogger(__name__)


class TranscriptionWorker(QThread):
    """One-shot QThread that transcribes a single audio chunk."""

    def __init__(
        self,
        stt_client: GroqSTTClient,
        audio_bytes: bytes,
        speaker: str = "Meeting",
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._stt = stt_client
        self._audio = audio_bytes
        self._speaker = speaker

    def run(self) -> None:
        self._stt.transcribe(self._audio, self._speaker)


class AdvisorWorker(QThread):
    """One-shot QThread that generates questions from transcript context."""

    def __init__(
        self,
        llm_client: GroqLLMClient,
        context: str,
        word_count: int,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._llm = llm_client
        self._context = context
        self._word_count = word_count

    def run(self) -> None:
        self._llm.generate_questions(self._context, self._word_count)


class Orchestrator(QObject):
    """Central coordinator — subscribes to events and wires the pipeline."""

    def __init__(self, settings: Settings, api_key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.buffer = RollingTranscriptBuffer(settings)
        self.capture = AudioCaptureManager()
        self.stt = GroqSTTClient(settings, api_key=api_key)
        self.llm = GroqLLMClient(settings, api_key=api_key)
        self.logger = SessionLogger()

        # Keep references to active workers so they aren't GC'd
        self._active_workers: list[QThread] = []

        # Wire EventBus subscriptions
        bus = get_bus()
        # Use subscribe_qt for handlers that create QThread workers
        subscribe_qt(AudioChunkReady, self._on_chunk, parent=self)
        subscribe_qt(TranscriptSegmentAdded, self._on_segment, parent=self)
        
        bus.subscribe(QuestionsReady, self.logger.on_questions)
        bus.subscribe(QuestionsReady, self._on_questions)
        bus.subscribe(ErrorOccurred, self._on_error)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin a new session and start audio capture."""
        self.logger.begin_session()
        self.capture.start(self._settings, parent=self)
        get_bus().emit(ListeningStateChanged(is_listening=True))
        logger.info("Orchestrator started")

    def stop(self) -> None:
        """Stop audio capture and end the session."""
        self.capture.stop()
        get_bus().emit(ListeningStateChanged(is_listening=False))
        logger.info("Orchestrator stopped")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_chunk(self, event: AudioChunkReady) -> None:
        """Dispatch audio chunk to TranscriptionWorker."""
        worker = TranscriptionWorker(
            stt_client=self.stt,
            audio_bytes=event.audio,
            speaker="Meeting",
            parent=self,
        )
        self._track_worker(worker)
        worker.start()

    def _on_segment(self, event: TranscriptSegmentAdded) -> None:
        """Add segment to buffer, log it, and trigger LLM if threshold met."""
        self.buffer.add(event)
        self.logger.on_segment(event)

        # Print to terminal
        print(f"[{event.timestamp:%H:%M:%S}] {event.speaker}: {event.text}")

        if self.buffer.should_trigger():
            ctx = self.buffer.get_context_string()
            word_count = self.buffer.total_word_count
            self.buffer.reset_trigger_count()

            worker = AdvisorWorker(
                llm_client=self.llm,
                context=ctx,
                word_count=word_count,
                parent=self,
            )
            self._track_worker(worker)
            worker.start()

    def _on_questions(self, event: QuestionsReady) -> None:
        """Print questions to terminal (Phase 2/3 fallback)."""
        print(f"\n--- QUESTIONS (context: {event.context_word_count} words) ---")
        for i, q in enumerate(event.questions, start=1):
            print(f"  {i}. {q}")
        print()

    def _on_error(self, event: ErrorOccurred) -> None:
        """Handle errors — stop if not recoverable."""
        logger.error(
            "[%s] %s (recoverable=%s)",
            event.source,
            event.message,
            event.recoverable,
        )
        if not event.recoverable:
            logger.critical("Fatal error from %s — stopping", event.source)
            self.stop()

    # ------------------------------------------------------------------
    # Worker management
    # ------------------------------------------------------------------

    def _track_worker(self, worker: QThread) -> None:
        """Track worker and auto-remove on completion."""
        self._active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._remove_worker(w))  # type: ignore[misc]
        worker.finished.connect(worker.deleteLater)

    def _remove_worker(self, worker: QThread) -> None:
        """Remove a completed worker from the active list."""
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass
