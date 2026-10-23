"""Orchestrator — wires all layers together via EventBus subscriptions.

The Orchestrator is the only module that knows about all layers. It is
instantiated once in ``__main__.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QThread

from meeting_copilot.application.event_bus import get_bus, subscribe_qt
from meeting_copilot.application.transcript_buffer import RollingTranscriptBuffer
from meeting_copilot.domain.events import (
    AnswerReady,
    AudioChunkReady,
    ClearContextRequested,
    ContextCleared,
    ErrorOccurred,
    ListeningStateChanged,
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
        context_generation: int = 0,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._stt = stt_client
        self._audio = audio_bytes
        self._speaker = speaker
        self._context_generation = context_generation

    def run(self) -> None:
        self._stt.transcribe(
            self._audio,
            self._speaker,
            context_generation=self._context_generation,
        )


class AdvisorWorker(QThread):
    """One-shot QThread that generates answer guidance from transcript context."""

    def __init__(
        self,
        llm_client: GroqLLMClient,
        context: str,
        word_count: int,
        context_generation: int,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._llm = llm_client
        self._context = context
        self._word_count = word_count
        self._context_generation = context_generation

    def run(self) -> None:
        self._llm.generate_answer(
            self._context,
            self._word_count,
            context_generation=self._context_generation,
        )


class Orchestrator(QObject):
    """Central coordinator — subscribes to events and wires the pipeline."""

    def __init__(self, settings: Settings, api_key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.buffer = RollingTranscriptBuffer(settings)
        self._context_generation = 0
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
        subscribe_qt(ClearContextRequested, self._on_clear_context, parent=self)

        bus.subscribe(AnswerReady, self._on_answer_event)
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

    def shutdown(self) -> None:
        """Stop capture and wait for API workers before Qt destroys their parent."""
        self.stop()
        for worker in list(self._active_workers):
            worker.wait()
        self._active_workers.clear()
        logger.info("Orchestrator workers stopped")

    def _on_clear_context(self, _event: ClearContextRequested) -> None:
        """Clear current interview context without deleting session history."""
        self._context_generation += 1
        self.buffer.clear()
        self.capture.clear_context(self._context_generation)
        get_bus().emit(ContextCleared(generation=self._context_generation))
        logger.info(
            "Cleared interview context (generation %d)",
            self._context_generation,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_chunk(self, event: AudioChunkReady) -> None:
        """Dispatch audio chunk to TranscriptionWorker."""
        worker = TranscriptionWorker(
            stt_client=self.stt,
            audio_bytes=event.audio,
            speaker="Meeting",
            context_generation=event.context_generation,
            parent=self,
        )
        self._track_worker(worker)
        worker.start()

    def _on_segment(self, event: TranscriptSegmentAdded) -> None:
        """Add segment to buffer, log it, and trigger LLM if threshold met."""
        if event.context_generation != self._context_generation:
            logger.debug(
                "Ignoring transcript from cleared context generation %d",
                event.context_generation,
            )
            return

        self.buffer.add(event)
        self.logger.on_segment(event)

        # Print to terminal
        print(f"[{event.timestamp:%H:%M:%S}] {event.speaker}: {event.text}")

        if event.speaker == "Meeting" or self.buffer.should_trigger():
            ctx = self.buffer.get_context_string()
            word_count = self.buffer.total_word_count
            self.buffer.reset_trigger_count()

            worker = AdvisorWorker(
                llm_client=self.llm,
                context=ctx,
                word_count=word_count,
                context_generation=self._context_generation,
                parent=self,
            )
            self._track_worker(worker)
            worker.start()

    def _on_answer_event(self, event: AnswerReady) -> None:
        """Ignore completed answer requests from before the last clear."""
        if event.context_generation != self._context_generation:
            logger.debug(
                "Ignoring answer from cleared context generation %d",
                event.context_generation,
            )
            return
        self.logger.on_answer(event)
        self._on_answer(event)

    def _on_answer(self, event: AnswerReady) -> None:
        """Print answer guidance to terminal for troubleshooting."""
        print(f"\n--- ANSWER GUIDANCE (context: {event.context_word_count} words) ---")
        print(event.answer)
        for point in event.talking_points:
            print(f"  • {point}")
        if event.follow_up:
            print(f"  Clarify: {event.follow_up}")
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
        worker.finished.connect(lambda w=worker: self._remove_worker(w))
        worker.finished.connect(worker.deleteLater)

    def _remove_worker(self, worker: QThread) -> None:
        """Remove a completed worker from the active list."""
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass
